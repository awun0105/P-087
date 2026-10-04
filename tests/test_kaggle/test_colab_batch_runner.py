"""Proof local cho transfer/resume; không thay cho Colab/GPU acceptance."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from threading import Event

import pytest

from scripts.colab import batch_colab_runner as runner
from scripts.kaggle.job_bundle import BundleFile, JobBundle, load_bundle


def _bundle(root: Path, content: bytes) -> Path:
    """Fixture đúng schema tại transfer boundary, không phải reconstruction thật."""
    source = root / "job-transfer"
    artifact = source / "artifacts/jobs/job-transfer/input.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(content)
    manifest = JobBundle(
        job_id="job-transfer",
        project_id="project-transfer",
        job_version=1,
        manifest_ref="artifact://jobs/job-transfer/manifest.json",
        project_payload="{}",
        events={1: "{}"},
        uploads={},
        files=[
            BundleFile(
                path="jobs/job-transfer/input.bin", size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest()
            )
        ],
    )
    (source / "bundle.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return source


def _transport(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, corrupt: bool = False) -> Path:
    """Giả Contents transport; archive/checksum/extraction dùng code thật."""
    source = _bundle(tmp_path / "remote", b"published artifact")
    archive = tmp_path / "archive.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(source, arcname=source.name)
    data = archive.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    manifest = {"sha256": checksum, "parts": [{"name": "part-00000", "sha256": checksum, "size": len(data)}]}
    monkeypatch.setattr(runner, "_remote_idempotent", lambda *args: "BUNDLE_TRANSFER " + json.dumps(manifest))

    def download(command: list[str]) -> None:
        target = Path(command[-1])
        if corrupt:
            target.write_bytes(b"broken transfer")
        else:
            shutil.copyfile(archive, target)

    monkeypatch.setattr(runner, "_transfer", download)
    return source


def test_bundle_transfer_verifies_and_resumes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = _transport(monkeypatch, tmp_path)
    destination = runner._download_bundle("test", "/content/bundles/job-transfer", tmp_path / "local")
    assert load_bundle(destination) == load_bundle(source)
    monkeypatch.setattr(runner, "_transfer", lambda command: pytest.fail("Verified part downloaded again"))
    assert runner._download_bundle("test", "/content/bundles/job-transfer", tmp_path / "local") == destination


def test_corrupt_transfer_never_publishes_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _transport(monkeypatch, tmp_path, corrupt=True)
    with pytest.raises(RuntimeError, match="sai checksum"):
        runner._download_bundle("test", "/content/bundles/job-transfer", tmp_path / "local")
    assert not (tmp_path / "local/job-transfer").exists()


def test_existing_different_bundle_is_preserved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _transport(monkeypatch, tmp_path)
    existing = _bundle(tmp_path / "local", b"existing artifact")
    before = load_bundle(existing)
    with pytest.raises(RuntimeError, match="không ghi đè"):
        runner._download_bundle("test", "/content/bundles/job-transfer", tmp_path / "local")
    assert load_bundle(existing) == before


def test_remote_zero_exit_without_marker_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "Remote exception mentions MARKER", ""),
    )
    with pytest.raises(RuntimeError, match="chưa xác nhận MARKER"):
        runner._remote_idempotent("test", "raise RuntimeError()", "MARKER")


def test_failed_job_recovery_script_is_valid_python(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Recovery thiếu bundle phải gửi Python hợp lệ và giữ trạng thái thất bại."""
    scripts: list[str] = []

    def remote(session: str, code: str, marker: str) -> str:
        compile(code, "<remote-recovery>", "exec")
        scripts.append(code)
        return "RECOVERY_BUNDLE /content/bundles/SC-01/recovery/job-transfer"

    monkeypatch.setattr(runner, "_remote_idempotent", remote)
    monkeypatch.setattr(runner, "_capture_logs", lambda *args: None)
    monkeypatch.setattr(runner, "_download_bundle", lambda *args: tmp_path / "job-transfer")
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, "", "Import fixture deliberately unavailable"),
    )
    args = argparse.Namespace(session="test", out_dir=tmp_path)
    assert not runner._collect_scenario(
        args,
        "SC-01",
        "scene",
        "test",
        "test",
        "job: job-transfer ← fixture\nP087_REMOTE_EXIT=1",
        tmp_path / "runtime.json",
    )
    assert len(scripts) == 1


def test_collection_does_not_block_next_gpu_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Một collector local chờ; producer vẫn được bắt đầu job GPU tiếp theo."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "video.mp4").write_bytes(b"fixture")
    (inputs / "manifest.json").write_text(
        json.dumps(
            {
                "scenarios": [
                    {"code": code, "folder": ".", "video": "video.mp4", "sensor": "Chỉ Video"}
                    for code in ["SC-01", "SC-03"]
                ]
            }
        )
    )
    collecting, next_gpu = Event(), Event()
    monkeypatch.setattr(runner, "_capture_runtime", lambda *args: tmp_path / "runtime.json")
    monkeypatch.setattr(runner, "upload_to_colab", lambda *args, **kwargs: None)

    def gpu_run(*args: object) -> str:
        if args[1] == "SC-03":
            assert collecting.wait(1), "Collector chưa bắt đầu"
            next_gpu.set()
        return "P087_REMOTE_EXIT=0"

    def collect(*args: object) -> bool:
        collecting.set()
        assert next_gpu.wait(2), "Download artifact chặn lượt GPU kế tiếp"
        return True

    monkeypatch.setattr(runner, "_run_detached", gpu_run)
    monkeypatch.setattr(runner, "_collect_scenario", collect)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "batch",
            "--scenes-dir",
            str(inputs),
            "--out-dir",
            str(tmp_path / "out"),
            "--demo-library-dir",
            str(tmp_path / "library"),
        ],
    )
    assert runner.main() == 0
