"""REC-04 fixture orchestration và real splat-transform codec proof tách biệt."""

import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.services.orchestration.artifacts.errors import ArtifactChecksumError
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.adapters.brush import BrushAdapter, BrushDependencies, BrushRequest
from src.services.reconstruction.adapters.brush_input import BrushInputAdapter
from src.services.reconstruction.adapters.brush_runtime import (
    BrushRuntimeSettings,
    Invocation,
    VisualError,
    VisualProcess,
    brush_command,
)
from src.services.reconstruction.adapters.colmap import ColmapAdapter, ColmapDependencies, ColmapRequest
from src.services.reconstruction.adapters.splat import SplatArtifactProcessor, SplatRuntimeSettings
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.splat.visual import BrushConfig, BrushVisualArtifact, SplatInspection
from src.services.reconstruction.rgb.splat.visual_publication import VisualPublisher, VisualResolver
from tests.test_reconstruction.test_rec03_colmap import FixtureProcess, frame_source, reference
from tests.test_reconstruction.test_rec03_colmap import config as colmap_config


def config() -> BrushConfig:
    """Config nhỏ explicit cho fixture, không là training quality policy."""
    return BrushConfig(
        total_train_iters=10,
        max_resolution=128,
        sh_degree=0,
        seed=0,
        max_splats=1000,
        refine_every=200,
        sog_iterations=1,
    )


def png_frames(root: Path) -> tuple:
    """Dùng fixture REC-03 nhưng cung cấp PNG thật để kiểm tra image/intrinsics."""
    frames, ref = frame_source(root)
    path = frames._resolve(ref)
    payload = json.loads(path.read_text())
    for frame in payload["frames"]:
        image = root / f"{frame['frame_id']:06d}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=640x480",
                "-frames:v",
                "1",
                "-threads",
                "1",
                "-y",
                str(image),
            ],
            check=True,
        )
        image_ref = reference(image.name, image.read_bytes(), "RGBFrame")
        frame.update(image=image_ref.model_dump(mode="json"), source_checksum=image_ref.artifact_checksum)
    payload["frame_set_checksum"] = canonical_content_checksum(payload, "frame_set_checksum")
    path.write_text(json.dumps(payload))
    return frames, reference(path.name, path.read_bytes(), "NormalizedRGBFrameSet")


def gaussian_ply(path: Path, mode: str = "valid") -> None:
    """Binary PLY fixture; production reader/codec đến từ upstream."""
    fields = "x y z f_dc_0 f_dc_1 f_dc_2 opacity scale_0 scale_1 scale_2 rot_0 rot_1 rot_2 rot_3".split()
    if mode == "plain":
        fields = fields[:3]
    header = "ply\nformat binary_little_endian 1.0\nelement vertex 256\n"
    header += "".join(f"property float {field}\n" for field in fields) + "end_header\n"
    rows = []
    for i in range(256):
        xyz = [i % 16 / 16, i // 16 / 16, 3.0]
        values = xyz + [0.1, 0.2, 0.3, 1, -3, -3, -3, 1, 0, 0, 0]
        if mode == "nan":
            values[0] = float("nan")
        if mode == "quaternion":
            values[10] = 0
        rows.append(struct.pack("<" + "f" * len(fields), *values[: len(fields)]))
    path.write_bytes(header.encode() + b"".join(rows))
    if mode == "truncated":
        path.write_bytes(path.read_bytes()[:-30])


class FixtureBrush(VisualProcess):
    """Không giả lập quality/GPU; chỉ orchestration qua real input/store/resolver."""

    def __init__(self) -> None:
        super().__init__(BrushRuntimeSettings(expected_version="0.3.0", runtime_identity="fixture"))

    def run(self, invocation: Invocation, workspace: Path) -> str:
        if invocation.name == "brush-version":
            text = "brush-cli 0.3.0"
        elif invocation.name == "brush-help":
            text = " ".join(brush_command(config(), workspace, "--total-steps"))
        else:
            gaussian_ply(workspace / "output/visual.ply")
            text = "fixture training"
        (workspace / f"{invocation.name}.log").write_text(text)
        return text


class FixtureProcessor(SplatArtifactProcessor):
    """Inspection fixture tách rõ với real-codec tests bên dưới."""

    def process_artifact(self, workspace: Path, iterations: int) -> SplatInspection:
        (workspace / "output/scene.sog").write_bytes(b"fixture SOG")
        return SplatInspection(
            version="3.6.6",
            revision="fixture",
            gaussian=True,
            num_gaussians=256,
            sh_bands=0,
            fill_ratio=1,
            nonfinite_count=0,
            ply_to_sog="identity_in_ply_storage_space",
            info={},
            stats={},
        )


def adapter(root: Path) -> tuple[BrushAdapter, BrushRequest]:
    """Published REC-03 fixture đi qua real REC-04 input validation."""
    frames, ref = png_frames(root / "source")
    store = ArtifactResolver(root / "store")
    writer = FilesystemArtifactStore(store)
    colmap = ColmapAdapter(ColmapDependencies(frames, FixtureProcess(), writer, store.require))
    poses_ref = colmap.execute(ColmapRequest(ref, colmap_config(), root / "sfm", "rec03-fixture")).reference
    poses = CameraPoseResolver(store.require, frames)
    process = FixtureBrush()
    processor = FixtureProcessor(SplatRuntimeSettings(module_path=root / "fixture.mjs"), process)
    deps = BrushDependencies(
        BrushInputAdapter(poses),
        process,
        processor,
        VisualPublisher(writer, "rec04-fixture"),
        VisualResolver(store.require, poses),
    )
    return BrushAdapter(deps), BrushRequest(poses_ref, config(), root / "brush")


def test_published_consumer_and_registered_only(tmp_path: Path) -> None:
    service, request = adapter(tmp_path)
    result = service.execute(request)
    assert result.stage.status.value == "SUCCEEDED"
    assert result.artifact.training_frame_ids == [0, 1, 2]
    assert len(list((request.workspace / "training/images").iterdir())) == 3
    assert result.artifact.scale_status == "arbitrary_sfm"
    assert service.deps.resolver.load(result.reference) == result.artifact
    (request.workspace / "output/visual.ply").write_bytes(b"temp changed")
    assert service.deps.resolver.load(result.reference) == result.artifact
    service.deps.resolver.require(result.artifact.delivery).write_bytes(b"tamper")
    with pytest.raises(ArtifactChecksumError):
        service.deps.resolver.load(result.reference)


@pytest.mark.parametrize("failure", ["missing", "tamper", "workspace", "writer"])
def test_failures_do_not_publish_success(tmp_path: Path, failure: str) -> None:
    service, request = adapter(tmp_path)
    if failure == "missing":
        service.deps.inputs.poses.require(request.camera_poses).unlink()
    elif failure == "tamper":
        (tmp_path / "source/000001.png").write_bytes(b"changed")
    elif failure == "workspace":
        request.workspace.mkdir()
    else:

        class BrokenWriter:
            def publish(self, ref: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
                raise OSError("storage failed")

        service.deps.publisher.writer = BrokenWriter()
    with pytest.raises(VisualError) as error:
        service.execute(request)
    assert error.value.to_failed_stage().status.value == "FAILED"
    assert not list((tmp_path / "store").rglob("visual.json"))


@pytest.mark.parametrize("flag", ["--total-steps", "--total-train-iters"])
def test_config_and_command(flag: str) -> None:
    args = brush_command(config(), Path("/tmp/rec04-test"), flag)
    assert args[args.index(flag) + 1] == "10"
    assert "--sog-iterations" not in args
    assert "--eval-split-every" not in args
    assert config().checksum() != config().model_copy(update={"seed": 1}).checksum()


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing"])
def test_real_process_failure(tmp_path: Path, failure: str) -> None:
    process = VisualProcess(
        BrushRuntimeSettings(expected_version="fixture", runtime_identity="fixture", timeout_seconds=0.1)
    )
    command = ("/nonexistent-rec04-tool",) if failure == "missing" else (sys.executable,)
    code = "import time; time.sleep(30)" if failure == "timeout" else "raise SystemExit(7)"
    with pytest.raises(VisualError) as error:
        process.run(Invocation("failure", command, ("-c", code)), tmp_path)
    expected = {"exit": "VISUAL_PROCESS_FAILED", "timeout": "VISUAL_TIMEOUT", "missing": "VISUAL_RUNTIME_UNAVAILABLE"}
    assert error.value.code == expected[failure]


@pytest.mark.parametrize("mode", ["valid", "plain", "nan", "quaternion", "truncated"])
def test_real_splat_codec(tmp_path: Path, mode: str) -> None:
    module = os.environ.get("REC04_TEST_SPLAT_MODULE")
    if not module:
        pytest.skip("Explicit pinned splat-transform runtime required")
    (tmp_path / "output").mkdir()
    master = tmp_path / "output/visual.ply"
    gaussian_ply(master, mode)
    before = hashlib.sha256(master.read_bytes()).hexdigest()
    process = VisualProcess(BrushRuntimeSettings(expected_version="fixture", runtime_identity="fixture"))
    processor = SplatArtifactProcessor(SplatRuntimeSettings(module_path=Path(module)), process)
    if mode == "valid":
        result = processor.process_artifact(tmp_path, 1)
        assert result.num_gaussians == 256 and result.revision != "fixture"
        assert (tmp_path / "output/scene.sog").stat().st_size > 0
    else:
        with pytest.raises(VisualError):
            processor.process_artifact(tmp_path, 1)
    assert hashlib.sha256(master.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("modern", [True, False])
def test_runtime_capability_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, modern: bool) -> None:
    """Runtime flags lấy từ help, không từ version của source checkout."""
    process = FixtureBrush()
    flag = "--total-train-iters" if modern else "--total-steps"
    outputs = {"brush-version": "brush-cli 0.3.0", "brush-help": " ".join(brush_command(config(), tmp_path, flag))}
    monkeypatch.setattr(process, "run", lambda invocation, workspace: outputs[invocation.name])
    assert process.qualify(tmp_path) == "brush-cli 0.3.0"
    assert process.iteration_flag == flag
    outputs["brush-version"] = "brush-cli 1.0.0"
    with pytest.raises(VisualError, match="version"):
        process.qualify(tmp_path)
    outputs.update({"brush-version": "brush-cli 0.3.0", "brush-help": "unknown cli"})
    with pytest.raises(VisualError, match="controls"):
        process.qualify(tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("config_checksum", "sha256:" + "a" * 64),
        ("training_frame_ids", [2, 1, 0]),
        ("parent_frame", "world"),
        ("scale_status", "confirmed"),
    ],
)
def test_internal_manifest_invariants(tmp_path: Path, field: str, value: object) -> None:
    service, request = adapter(tmp_path)
    payload = service.execute(request).artifact.model_dump(mode="json")
    payload[field] = value
    payload["artifact_checksum"] = canonical_content_checksum(payload, "artifact_checksum")
    with pytest.raises(ValueError):
        BrushVisualArtifact.model_validate(payload)


@pytest.mark.parametrize("change", [{"num_gaussians": 1001}, {"sh_bands": 1}])
def test_training_budget_and_sh_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict) -> None:
    service, request = adapter(tmp_path)
    original = service.deps.processor.process_artifact

    def inspect(workspace: Path, iterations: int) -> SplatInspection:
        return original(workspace, iterations).model_copy(update=change)

    monkeypatch.setattr(service.deps.processor, "process_artifact", inspect)
    with pytest.raises(VisualError):
        service.execute(request)
    assert not list((tmp_path / "store").rglob("visual.json"))


@pytest.mark.parametrize("failure", ["intrinsics", "args", "pose"])
def test_bridge_invariants(tmp_path: Path, failure: str) -> None:
    service, request = adapter(tmp_path)
    result = service.execute(request)
    root = request.workspace / "training"
    if failure == "args":
        (root / "args.txt").write_text("--seed 999")
    else:
        path = root / "sparse/0" / ("cameras.txt" if failure == "intrinsics" else "images.txt")
        text = path.read_text()
        path.write_text(
            text.replace("640 480", "320 240")
            if failure == "intrinsics"
            else text.replace("1 1 0 0 0 0", "1 1 0 0 0 5")
        )
    poses = service.deps.resolver.poses.load(result.artifact.source_camera_poses)
    with pytest.raises(ValueError):
        BrushInputAdapter._verify_training(request.workspace, poses)


def test_store_corruption_prevents_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, request = adapter(tmp_path)
    writer = service.deps.publisher.writer
    publish = writer.publish

    def corrupt(ref: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        result = publish(ref, payload)
        service.deps.resolver.resolve(ref).write_bytes(b"corrupt store")
        return result

    monkeypatch.setattr(writer, "publish", corrupt)
    with pytest.raises(VisualError):
        service.execute(request)
    assert not list((tmp_path / "store").rglob("visual.json"))
