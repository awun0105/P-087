"""Kho resume (COLMAP đã xong + checkpoint Brush) và lệnh Brush khi checkpoint/train tiếp."""

import struct
from pathlib import Path

from src.services.reconstruction.adapters.brush_runtime import Checkpointing, brush_command
from src.services.reconstruction.resume import ResumeCache, checkpoint_interval, content_key, ply_is_complete
from tests.test_reconstruction.test_rec04_brush import config


def _ply(path: Path, count: int, *, truncate: int = 0) -> Path:
    header = f"ply\nformat binary_little_endian 1.0\nelement vertex {count}\nproperty float x\nproperty float y\nend_header\n"
    body = b"".join(struct.pack("<ff", float(i), 0.0) for i in range(count))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header.encode() + body[: len(body) - truncate])
    return path


def _colmap_workspace(root: Path, marker: str) -> Path:
    (root / "sparse" / "0").mkdir(parents=True)
    (root / "sparse" / "0" / "points3D.bin").write_text(marker)
    (root / "process.log").write_text(f"log {marker}\n")
    return root


def test_ply_complete_detects_truncated_checkpoint(tmp_path: Path) -> None:
    assert ply_is_complete(_ply(tmp_path / "ok.ply", 10))
    assert not ply_is_complete(_ply(tmp_path / "cut.ply", 10, truncate=3))
    (tmp_path / "junk.ply").write_bytes(b"not a ply")
    assert not ply_is_complete(tmp_path / "junk.ply")
    assert not ply_is_complete(tmp_path / "missing.ply")


def test_latest_checkpoint_skips_truncated_and_final_step(tmp_path: Path) -> None:
    cache = ResumeCache(tmp_path)
    directory = cache.checkpoint_dir("k")
    _ply(directory / "ckpt_02500.ply", 4)  # Brush đệm số 0 theo độ dài tổng số bước
    _ply(directory / "ckpt_05000.ply", 4)
    _ply(directory / "ckpt_7500.ply", 4, truncate=1)  # đang ghi dở lúc máy tắt
    _ply(directory / "ckpt_30000.ply", 4)  # bước cuối không phải điểm để train tiếp
    cache.attest_checkpoints("k", {})  # mô phỏng child đã dừng sau khi xuất các checkpoint hoàn chỉnh

    assert cache.latest_checkpoint("k", 30000) == (5000, directory / "ckpt_05000.ply")
    assert cache.checkpoints("k")[30000] == directory / "ckpt_30000.ply"
    assert cache.latest_checkpoint("khác", 30000) is None
    cache.clear_checkpoints("k")
    assert cache.latest_checkpoint("k", 30000) is None


def test_brush_checkpoint_needs_attestation_and_checksum_match(tmp_path: Path) -> None:
    cache = ResumeCache(tmp_path)
    directory = cache.checkpoint_dir("resume-key")
    checkpoint = _ply(directory / "ckpt_02500.ply", 4)

    # Một worker bị tắt đột ngột chưa ghi receipt thì không được resume file dù PLY đủ chiều dài.
    assert cache.latest_checkpoint("resume-key", 30000) is None
    cache.attest_checkpoints("resume-key", {})
    assert cache.latest_checkpoint("resume-key", 30000) == (2500, checkpoint)

    original = checkpoint.read_bytes()
    data_offset = original.index(b"end_header\n") + len(b"end_header\n")
    corrupted = bytearray(original)
    corrupted[data_offset] ^= 1  # cùng kích thước và vẫn có header hợp lệ
    checkpoint.write_bytes(corrupted)
    assert checkpoint.stat().st_size == len(original)
    assert cache.latest_checkpoint("resume-key", 30000) is None


def test_legacy_brush_cache_is_ignored_and_preserved(tmp_path: Path) -> None:
    cache = ResumeCache(tmp_path)
    legacy = tmp_path / "brush-old-key"
    _ply(legacy / "ckpt_05000.ply", 4)

    assert cache.latest_checkpoint("old-key", 30000) is None
    assert legacy.joinpath("ckpt_05000.ply").is_file()
    assert cache.checkpoint_dir("old-key") != legacy


def test_colmap_restore_copies_finished_model_and_marks_log(tmp_path: Path) -> None:
    resume_root = tmp_path / "resume"
    cache = ResumeCache(resume_root)
    fresh = tmp_path / "attempt-2"
    fresh.mkdir()
    assert cache.restore_colmap("k", fresh) is False and not (fresh / "sparse").exists()

    cache.store_colmap("k", _colmap_workspace(tmp_path / "attempt-1", "A"))

    (fresh / "process.log").write_text("probe\n")
    assert ResumeCache(resume_root).restore_colmap("k", fresh) is True  # new cache object simulates worker restart
    assert (fresh / "sparse/0/points3D.bin").read_text() == "A"
    log = (fresh / "process.log").read_text()
    assert log.startswith("probe\n") and "REUSED_SPARSE_MODEL key=k" in log and "log A" in log


def test_corrupt_colmap_cache_is_a_miss_and_is_preserved_when_repaired(tmp_path: Path) -> None:
    resume_root = tmp_path / "resume"
    cache = ResumeCache(resume_root)
    cache.store_colmap("k", _colmap_workspace(tmp_path / "attempt-1", "A"))
    corrupt_file = cache._colmap("k") / "sparse/0/points3D.bin"
    corrupt_file.write_bytes(b"X")  # giữ nguyên độ dài nhưng phá checksum

    fresh = tmp_path / "attempt-2"
    fresh.mkdir()
    assert ResumeCache(resume_root).restore_colmap("k", fresh) is False
    assert not (fresh / "sparse").exists()

    cache.store_colmap("k", _colmap_workspace(tmp_path / "attempt-2-cold", "B"))
    quarantine = list(resume_root.glob(".invalid-colmap-k-*"))
    assert len(quarantine) == 1
    assert (quarantine[0] / "sparse/0/points3D.bin").read_bytes() == b"X"

    repaired = tmp_path / "attempt-3"
    repaired.mkdir()
    assert cache.restore_colmap("k", repaired) is True
    assert (repaired / "sparse/0/points3D.bin").read_text() == "B"


def test_new_sparse_model_invalidates_checkpoints_of_old_one(tmp_path: Path) -> None:
    cache = ResumeCache(tmp_path / "resume")
    cache.store_colmap("k", _colmap_workspace(tmp_path / "a1", "A"))
    _ply(cache.checkpoint_dir("k") / "ckpt_5000.ply", 4)

    # COLMAP chạy lại (kho bị xoá tay, cấu hình như cũ): hệ toạ độ mới → checkpoint cũ không dùng được.
    cache.store_colmap("k", _colmap_workspace(tmp_path / "a2", "B"))

    assert cache.latest_checkpoint("k", 30000) is None
    target = tmp_path / "a3"
    target.mkdir()
    cache.restore_colmap("k", target)
    assert (target / "sparse/0/points3D.bin").read_text() == "B"


def test_content_key_and_interval() -> None:
    assert content_key("a", "b") == content_key("a", "b") != content_key("ab", "")
    key = content_key("frames", "config", "runtime", "tool", "guidance")
    assert all(
        content_key(*parts) != key
        for parts in (
            ("changed-frames", "config", "runtime", "tool", "guidance"),
            ("frames", "changed-config", "runtime", "tool", "guidance"),
            ("frames", "config", "changed-runtime", "tool", "guidance"),
            ("frames", "config", "runtime", "changed-tool", "guidance"),
            ("frames", "config", "runtime", "tool", "changed-guidance"),
        )
    )
    assert checkpoint_interval(30000, 2500) == 2500
    assert checkpoint_interval(7000, 2500) == 2333 or 7000 % checkpoint_interval(7000, 2500) == 0
    assert 7000 % checkpoint_interval(7000, 2500) == 0 and 1009 % checkpoint_interval(1009, 300) == 0


def test_brush_command_without_checkpointing_is_unchanged(tmp_path: Path) -> None:
    args = brush_command(config(), tmp_path, "--total-steps")
    total = str(config().total_train_iters)
    assert args[-6:] == (
        "--export-every",
        total,
        "--export-path",
        str((tmp_path / "output").resolve()),
        "--export-name",
        "visual.ply",
    )
    assert "--start-iter" not in args


def test_brush_command_checkpoints_and_resumes(tmp_path: Path) -> None:
    fresh = brush_command(config(), tmp_path, "--total-steps", Checkpointing(tmp_path / "ck", 2500))
    assert fresh[-6:] == (
        "--export-every",
        "2500",
        "--export-path",
        str((tmp_path / "ck").resolve()),
        "--export-name",
        "ckpt_{iter}.ply",
    )
    assert "--start-iter" not in fresh

    resumed = brush_command(config(), tmp_path, "--total-steps", Checkpointing(tmp_path / "ck", 2500, 5000))
    assert resumed[resumed.index("--start-iter") + 1] == "5000"
