"""REC-01: gộp ảnh RGB trùng giữa raw/ và normalized/ không được đổi bytes, manifest hay làm hỏng raw."""

import errno
import json
import os
import sys
from pathlib import Path

import pytest

from scripts.torwic import dedupe_rgb_frames as dedupe
from scripts.torwic.prepare_dataset import PrepConfig, compute_sha256, run_safely, validate_manifest_offline
from tests.test_reconstruction.test_rec01_dataset import _png_rgba, _setup_canonical_dataset

_MANIFEST = "derived/aisle_cw/preparation_manifest.json"
_RAW = "raw/traversals/aisle_cw/image_left"
_NORMALIZED = "normalized/aisle_cw/rgb_frames"
_NAMES = [f"{frame_id:06d}.png" for frame_id in range(4)]

needs_file_permissions = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root bỏ qua quyền file nên không kiểm được chỉ-đọc"
)


def _prepared_store(tmp_path: Path) -> tuple[Path, PrepConfig]:
    """Store canonical vừa publish: normalized là bản sao rời của raw."""
    root = _setup_canonical_dataset(tmp_path / "dataset")
    config = PrepConfig(ds_root=root, out_root=root, trav_id="Aisle_CW", train_ids=[0, 1, 2], held_ids=[3])
    run_safely(config)
    return root, config


def _raw_hashes(root: Path) -> list[str]:
    return [compute_sha256(path) for path in sorted((root / "raw").rglob("*")) if path.is_file()]


def _link_counts(root: Path) -> list[int]:
    return [(root / _NORMALIZED / name).stat().st_nlink for name in _NAMES]


def test_report_only_by_default_changes_nothing(tmp_path: Path) -> None:
    root, _ = _prepared_store(tmp_path)
    report = dedupe.dedupe_rgb_frames(root, apply=False)
    assert (report.frame_count, report.shared, report.duplicated, report.linked) == (4, 0, 4, 0)
    assert report.duplicated_bytes == sum((root / _NORMALIZED / name).stat().st_size for name in _NAMES)
    assert _link_counts(root) == [1, 1, 1, 1]


def test_apply_keeps_one_physical_copy_without_changing_bytes_or_manifests(tmp_path: Path) -> None:
    root, _ = _prepared_store(tmp_path)
    raw_before = _raw_hashes(root)
    markers = [compute_sha256(root / _MANIFEST), compute_sha256(root / "dataset_manifest.yaml")]

    report = dedupe.dedupe_rgb_frames(root, apply=True)

    assert (report.shared, report.duplicated, report.duplicated_bytes) == (4, 0, 0)
    assert (report.linked, report.writable_shared) == (4, 0)
    for name in _NAMES:
        normalized = root / _NORMALIZED / name
        assert os.path.samefile(root / _RAW / name, normalized)
        assert not normalized.is_symlink()
    assert _raw_hashes(root) == raw_before
    assert [compute_sha256(root / _MANIFEST), compute_sha256(root / "dataset_manifest.yaml")] == markers
    validate_manifest_offline(root / _MANIFEST, root, root)
    assert sorted(path.name for path in (root / _NORMALIZED).iterdir()) == _NAMES


def test_apply_twice_is_idempotent(tmp_path: Path) -> None:
    root, _ = _prepared_store(tmp_path)
    dedupe.dedupe_rgb_frames(root, apply=True)
    again = dedupe.dedupe_rgb_frames(root, apply=True)
    assert (again.shared, again.linked, again.writable_shared) == (4, 0, 0)
    assert _link_counts(root) == [2, 2, 2, 2]


@needs_file_permissions
def test_in_place_write_to_a_shared_frame_fails_and_raw_survives(tmp_path: Path) -> None:
    root, _ = _prepared_store(tmp_path)
    dedupe.dedupe_rgb_frames(root, apply=True)
    raw_before = _raw_hashes(root)
    with pytest.raises(PermissionError):
        (root / _NORMALIZED / "000000.png").write_bytes(_png_rgba(99))
    assert _raw_hashes(root) == raw_before
    validate_manifest_offline(root / _MANIFEST, root, root)


def test_replacing_a_shared_frame_detaches_it_and_the_store_is_rejected(tmp_path: Path) -> None:
    """Thay file bằng rename chỉ tách liên kết: raw nguyên vẹn, còn store lệch manifest thì bị từ chối."""
    root, config = _prepared_store(tmp_path)
    dedupe.dedupe_rgb_frames(root, apply=True)
    raw_before = _raw_hashes(root)
    image = root / _NORMALIZED / "000000.png"
    replacement = root / "replacement.tmp"
    replacement.write_bytes(_png_rgba(99))
    os.replace(replacement, image)

    assert _raw_hashes(root) == raw_before
    with pytest.raises(ValueError, match="Generated checksum mismatch"):
        dedupe.dedupe_rgb_frames(root, apply=True)
    with pytest.raises(ValueError, match="Canonical output differs"):
        run_safely(config)
    assert image.read_bytes() == _png_rgba(99)
    assert _raw_hashes(root) == raw_before


def test_invalid_store_is_refused_before_any_frame_is_touched(tmp_path: Path) -> None:
    root, _ = _prepared_store(tmp_path)
    (root / _NORMALIZED / "000002.png").write_bytes(_png_rgba(99))
    with pytest.raises(ValueError, match="Generated checksum mismatch"):
        dedupe.dedupe_rgb_frames(root, apply=True)
    assert _link_counts(root) == [1, 1, 1, 1]


def test_frame_changed_after_validation_is_not_replaced(tmp_path: Path) -> None:
    root, _ = _prepared_store(tmp_path)
    pairs = dedupe.load_frame_pairs(root)
    changed = root / _NORMALIZED / "000001.png"
    changed.write_bytes(_png_rgba(99))
    with pytest.raises(ValueError, match="changed after validation"):
        dedupe._replace_with_link(pairs[1])
    assert changed.read_bytes() == _png_rgba(99)
    assert changed.stat().st_nlink == 1


def test_filesystem_without_hard_links_is_reported_and_store_stays_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _prepared_store(tmp_path)

    def refuse(source: Path, target: Path) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    with monkeypatch.context() as patch:
        patch.setattr(dedupe.os, "link", refuse)
        with pytest.raises(ValueError, match="hard links"):
            dedupe.dedupe_rgb_frames(root, apply=True)
    assert _link_counts(root) == [1, 1, 1, 1]
    validate_manifest_offline(root / _MANIFEST, root, root)


def test_leftover_temp_link_from_an_interrupted_run_is_replaced(tmp_path: Path) -> None:
    root, _ = _prepared_store(tmp_path)
    stale = root / _NORMALIZED / ".000000.png.dedupe-tmp"
    stale.write_bytes(b"stale")
    report = dedupe.dedupe_rgb_frames(root, apply=True)
    assert report.shared == 4
    assert not stale.exists()


def test_publishing_again_after_dedupe_is_a_no_op_and_keeps_links(tmp_path: Path) -> None:
    root, config = _prepared_store(tmp_path)
    dedupe.dedupe_rgb_frames(root, apply=True)
    marker = compute_sha256(root / _MANIFEST)
    run_safely(config)
    assert compute_sha256(root / _MANIFEST) == marker
    assert _link_counts(root) == [2, 2, 2, 2]
    assert not list(root.parent.glob(".torwic_rec01_stage_*"))


def test_unprepared_store_is_reported_not_guessed(tmp_path: Path) -> None:
    root = _setup_canonical_dataset(tmp_path / "dataset")
    (root / "dataset_manifest.yaml").write_text("")
    with pytest.raises(ValueError, match="no prepared traversal"):
        dedupe.dedupe_rgb_frames(root, apply=True)


def test_cli_reports_by_default_and_applies_on_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = _prepared_store(tmp_path)
    monkeypatch.setattr(sys, "argv", ["dedupe_rgb_frames", "--dataset-root", str(root)])
    dedupe.main()
    assert json.loads(capsys.readouterr().out)["duplicated"] == 4
    assert _link_counts(root) == [1, 1, 1, 1]

    monkeypatch.setattr(sys, "argv", ["dedupe_rgb_frames", "--dataset-root", str(root), "--apply"])
    dedupe.main()
    applied = json.loads(capsys.readouterr().out)
    assert (applied["shared"], applied["linked"], applied["duplicated_bytes"]) == (4, 4, 0)


def test_cli_names_the_missing_component(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _setup_canonical_dataset(tmp_path / "dataset")
    monkeypatch.setattr(sys, "argv", ["dedupe_rgb_frames", "--dataset-root", str(root)])
    with pytest.raises(SystemExit, match="dataset_manifest.yaml"):
        dedupe.main()
