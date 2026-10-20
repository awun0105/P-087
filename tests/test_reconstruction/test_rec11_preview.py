"""Prepared preview fixture integration: real producer/consumer/store, không claim GPU training."""

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import StageId
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.orchestration.artifacts.errors import ArtifactAlreadyExistsError
from src.services.reconstruction import preview_cli
from src.services.reconstruction.adapters.brush_runtime import Invocation
from src.services.reconstruction.adapters.colmap_runtime import ColmapError
from src.services.reconstruction.adapters.splat import SplatArtifactProcessor, SplatRuntimeSettings
from src.services.reconstruction.preview_models import PreparedPreviewRequest, PreparedPreviewResult
from src.services.reconstruction.preview_worker import PreparedPreviewWorker, PreviewDependencies
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.splat.visual_publication import VisualResolver
from tests.test_reconstruction.test_rec03_colmap import FixtureProcess
from tests.test_reconstruction.test_rec03_colmap import config as colmap_config
from tests.test_reconstruction.test_rec04_brush import FixtureBrush, FixtureProcessor, png_frames
from tests.test_reconstruction.test_rec04_brush import config as brush_config


def publish_frames(root: Path, writer: FilesystemArtifactStore) -> tuple:
    """Tạo fixture job-bound trước producer execution, không remap output để né lineage."""
    frames, ref = png_frames(root / "source")
    inventory = frames.load(ref)
    for frame in inventory.frames:
        frame.image = frame.image.model_copy(update={"job_id": "input"})
        writer.publish(frame.image, frames._resolve(frame.image).read_bytes())
    inventory.frame_set_checksum = canonical_content_checksum(inventory, "frame_set_checksum")
    payload = inventory.model_dump_json().encode()
    ref = ref.model_copy(
        update={"job_id": "input", "artifact_checksum": "sha256:" + hashlib.sha256(payload).hexdigest()}
    )
    writer.publish(ref, payload)
    return inventory, ref


def preview(root: Path) -> tuple[PreparedPreviewWorker, PreparedPreviewRequest, ArtifactResolver]:
    """Frames fixture được publish qua cùng public artifact store như producer thật."""
    resolver = ArtifactResolver(root / "store")
    writer = FilesystemArtifactStore(resolver)
    inventory, ref = publish_frames(root, writer)
    request = PreparedPreviewRequest(
        job_id="input",
        attempt_id="first",
        source_input_checksum=inventory.input_manifest_checksum,
        frame_set_ref=ref,
        colmap=colmap_config(),
        brush=brush_config(),
    )
    brush = FixtureBrush()
    deps = PreviewDependencies(
        FrameSetResolver(resolver.require, resolver.require),
        writer,
        resolver.require,
        FixtureProcess(),
        brush,
        FixtureProcessor(SplatRuntimeSettings(module_path=root / "fixture.mjs"), brush),
    )
    return PreparedPreviewWorker(deps), request, resolver


def test_preview_handoff_and_durable_progress(tmp_path: Path) -> None:
    worker, request, resolver = preview(tmp_path)
    result, ref = worker.run(request, tmp_path / "run")
    assert result.preview_complete and result.job_status == "RUNNING" and result.metric_status == "UNCONFIRMED"
    assert PreparedPreviewResult.model_validate_json(resolver.require(ref).read_bytes()) == result
    assert worker.load(ref) == result
    assert [stage.stage_id for stage in result.stage_artifacts] == [StageId.CAMERA_POSE, StageId.VISUAL_RECON]
    assert all(stage.status == "SUCCEEDED" for stage in result.stage_artifacts)
    visuals = VisualResolver(resolver.require, CameraPoseResolver(resolver.require, worker.deps.frames))
    assert visuals.load(result.raw_visual_ref).source_camera_poses == result.camera_pose_ref
    assert resolver.require(result.delivery_ref).read_bytes() == b"fixture SOG"
    events = sorted((tmp_path / "store/jobs/input/attempts/first/rec11/events").glob("*.json"))
    assert [json.loads(path.read_bytes())["status"] for path in events] == ["RUNNING", "SUCCEEDED"] * 2
    assert str(tmp_path) not in result.model_dump_json()


def test_retry_preserves_job_and_previous_artifacts(tmp_path: Path) -> None:
    worker, request, resolver = preview(tmp_path)
    first, first_ref = worker.run(request, tmp_path / "run-first")
    original = resolver.require(first_ref).read_bytes()
    retry = request.model_copy(update={"attempt_id": "second"})
    second, second_ref = worker.run(retry, tmp_path / "run-second")
    assert first.preview_complete and second.preview_complete
    assert first.job_id == second.job_id and first.camera_pose_ref != second.camera_pose_ref
    assert first.raw_visual_ref != second.raw_visual_ref and first_ref != second_ref
    assert resolver.require(first_ref).read_bytes() == original
    assert first.raw_visual_ref.source_provenance["attempt_id"] == "first"
    with pytest.raises(ArtifactAlreadyExistsError):
        worker.run(request, tmp_path / "fresh-workspace-but-old-attempt")
    assert not (tmp_path / "fresh-workspace-but-old-attempt/colmap").exists()


@pytest.mark.parametrize("failure", ["source_identity", "frame_tamper", "colmap", "brush"])
def test_failure_is_durable_without_false_success(tmp_path: Path, failure: str) -> None:
    worker, request, resolver = preview(tmp_path)
    expected = StageId.FRAME_EXTRACT
    if failure == "source_identity":
        request = request.model_copy(update={"source_input_checksum": "sha256:" + "b" * 64})
    elif failure == "frame_tamper":
        frame = worker.deps.frames.load(request.frame_set_ref).frames[0]
        resolver.require(frame.image).write_bytes(b"changed")
    elif failure == "colmap":
        worker.deps.colmap.mode = "failed"
        expected = StageId.CAMERA_POSE
    else:
        worker = PreparedPreviewWorker(replace(worker.deps, brush=BrokenBrush()))
        expected = StageId.VISUAL_RECON
    result, ref = worker.run(request, tmp_path / "failure")
    assert not result.preview_complete and result.job_status == "FAILED"
    assert result.error.stage_id == expected and result.stage_artifacts[-1].status == "FAILED"
    assert result.delivery_ref is None and result.raw_visual_ref is None
    assert resolver.require(ref).is_file()
    assert "/private" not in result.model_dump_json()


def test_colmap_failure_keeps_its_code_and_redacted_log(tmp_path: Path) -> None:
    """The pod's attempt log is gone after release: the stored error is the only evidence left."""
    worker, request, _ = preview(tmp_path)
    worker = PreparedPreviewWorker(replace(worker.deps, colmap=LoggedFailure()))
    result, _ = worker.run(request, tmp_path / "failure")
    assert result.error.error_code == "COLMAP_NO_MODEL" and result.error.stage_id == StageId.CAMERA_POSE
    assert result.error.human_message == "COLMAP produced no sparse model"
    assert result.error.details["exception_type"] == "ColmapError"
    assert result.error.details["log_excerpt"] == "Discarding reconstruction due to no initial pair"
    assert str(tmp_path) not in result.model_dump_json()


class LoggedFailure(FixtureProcess):
    def capabilities(self, workspace: Path, matching_mode: str = "sequential") -> tuple[str, str, str]:
        raise ColmapError(
            "COLMAP_NO_MODEL",
            "COLMAP produced no sparse model",
            details={"log_excerpt": "Discarding reconstruction due to no initial pair"},
        )


class BrokenBrush(FixtureBrush):
    def run(self, invocation: Invocation, workspace: Path) -> str:
        raise OSError("/private/credential-like-runtime-path")


@pytest.mark.parametrize(
    "change",
    [
        {"attempt_id": "../old"},
        {"job_id": "foreign"},
        {"execution_scope": "full_pipeline"},
    ],
)
def test_invalid_dispatch_rejected(tmp_path: Path, change: dict) -> None:
    worker, request, _ = preview(tmp_path)
    with pytest.raises(ValueError):
        worker.run(request.model_copy(update=change), tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_cli_composition_uses_public_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    worker, request, resolver = preview(tmp_path)
    monkeypatch.setattr(preview_cli, "BrushRuntimeSettings", lambda: worker.deps.brush.settings)
    monkeypatch.setattr(preview_cli, "ColmapRuntimeSettings", lambda: worker.deps.colmap.settings)
    monkeypatch.setattr(preview_cli, "SplatRuntimeSettings", lambda: worker.deps.splat.settings)
    monkeypatch.setattr(preview_cli, "VisualProcess", lambda settings: worker.deps.brush)
    monkeypatch.setattr(preview_cli, "ColmapProcess", lambda settings: worker.deps.colmap)
    monkeypatch.setattr(preview_cli, "SplatArtifactProcessor", lambda settings, process: worker.deps.splat)
    path = tmp_path / "request.json"
    path.write_text(request.model_dump_json())
    args = ["--request", str(path), "--store-root", str(resolver.artifact_root), "--workspace", str(tmp_path / "cli")]
    assert preview_cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["preview_complete"] and payload["result"]["job_status"] == "RUNNING"
    assert preview_cli.main(args) == 2


def test_cli_module_missing_request_is_not_success() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "src.services.reconstruction.preview_cli"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and "--request" in result.stderr


def test_native_codec_through_preview_pipeline(tmp_path: Path) -> None:
    module = os.environ.get("REC04_TEST_SPLAT_MODULE")
    if not module:
        pytest.skip("REC04_TEST_SPLAT_MODULE required for native codec, not real training")
    worker, request, resolver = preview(tmp_path)
    # Runtime Node thật, trainer fixture; không gán qualification Brush GPU cho test này.
    from src.services.reconstruction.adapters.brush_runtime import VisualProcess

    processor = SplatArtifactProcessor(
        SplatRuntimeSettings(module_path=Path(module)), VisualProcess(worker.deps.brush.settings)
    )
    worker = PreparedPreviewWorker(replace(worker.deps, splat=processor))
    result, _ = worker.run(request, tmp_path / "native")
    assert result.preview_complete
    assert resolver.require(result.delivery_ref).read_bytes().startswith(b"PK")


@pytest.mark.parametrize("target", ["delivery", "poses", "request"])
def test_consumer_rejects_changed_dependency(tmp_path: Path, target: str) -> None:
    worker, request, resolver = preview(tmp_path)
    result, ref = worker.run(request, tmp_path / "run")
    dependency = {"delivery": result.delivery_ref, "poses": result.camera_pose_ref, "request": result.request_ref}[
        target
    ]
    resolver.require(dependency).write_bytes(b"corruption")
    with pytest.raises((ValueError, RuntimeError)):
        worker.load(ref)


def test_consumer_rejects_forged_stage_even_with_new_checksum(tmp_path: Path) -> None:
    worker, request, resolver = preview(tmp_path)
    result, ref = worker.run(request, tmp_path / "run")
    result.stage_artifacts[0].artifact_checksum = "sha256:" + "c" * 64
    payload = result.model_dump_json().encode()
    resolver.require(ref).write_bytes(payload)
    forged = ref.model_copy(update={"artifact_checksum": "sha256:" + hashlib.sha256(payload).hexdigest()})
    with pytest.raises(ValueError, match="stage differs"):
        worker.load(forged)


def test_cli_progress_file_streams_stage_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Orchestrator đọc được stage RUNNING/SUCCEEDED theo thứ tự trong lúc worker chạy."""
    from src.models.contracts.manifests import StageArtifact

    worker, request, resolver = preview(tmp_path)
    monkeypatch.setattr(preview_cli, "BrushRuntimeSettings", lambda: worker.deps.brush.settings)
    monkeypatch.setattr(preview_cli, "ColmapRuntimeSettings", lambda: worker.deps.colmap.settings)
    monkeypatch.setattr(preview_cli, "SplatRuntimeSettings", lambda: worker.deps.splat.settings)
    monkeypatch.setattr(preview_cli, "VisualProcess", lambda settings: worker.deps.brush)
    monkeypatch.setattr(preview_cli, "ColmapProcess", lambda settings: worker.deps.colmap)
    monkeypatch.setattr(preview_cli, "SplatArtifactProcessor", lambda settings, process: worker.deps.splat)
    path = tmp_path / "request.json"
    path.write_text(request.model_dump_json())
    progress = tmp_path / "progress.jsonl"
    args = [
        "--request", str(path), "--store-root", str(resolver.artifact_root),
        "--workspace", str(tmp_path / "cli"), "--progress-file", str(progress),
    ]  # fmt: skip
    assert preview_cli.main(args) == 0
    capsys.readouterr()
    events = [StageArtifact.model_validate_json(line) for line in progress.read_text().splitlines()]
    assert [(event.stage_id, event.status) for event in events] == [
        ("ST-CAMERA-POSE", "RUNNING"),
        ("ST-CAMERA-POSE", "SUCCEEDED"),
        ("ST-VISUAL-RECON", "RUNNING"),
        ("ST-VISUAL-RECON", "SUCCEEDED"),
    ]
