"""REC-03 unit/fixture proof; actual COLMAP smoke có evidence riêng."""

import hashlib
import json
import math
import subprocess
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.services.orchestration.artifacts.errors import ArtifactChecksumError
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.adapters.colmap import ColmapAdapter, ColmapDependencies, ColmapRequest
from src.services.reconstruction.adapters.colmap_model import read_sparse_model, select_sparse_model
from src.services.reconstruction.adapters.colmap_runtime import (
    ColmapError,
    ColmapProcess,
    ColmapRuntimeSettings,
    reconstruction_commands,
)
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.pose.camera_pose import CameraPoseArtifact, ColmapConfig
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver


def config(**changes: object) -> ColmapConfig:
    """Ngưỡng fixture explicit, không là policy Aisle_CW."""
    values = dict(
        camera_model="PINHOLE",
        single_camera=True,
        use_gpu=False,
        num_threads=2,
        max_image_size=1280,
        max_num_features=2048,
        sequential_overlap=5,
        random_seed=0,
        min_registered_frames=2,
        min_registered_ratio=0.5,
    )
    return ColmapConfig.model_validate(values | changes)


def sparse(directory: Path, ids: tuple[int, ...]) -> None:
    """Fixture pose identity và một sparse point; không giả lập reconstruction accuracy."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cameras.txt").write_text("# cameras\n1 PINHOLE 640 480 400 400 320 240\n")
    (directory / "images.txt").write_text(
        "# images\n" + "".join(f"{i + 1} 1 0 0 0 {i} 0 0 1 {i:06d}.png\n\n" for i in ids)
    )
    (directory / "points3D.txt").write_text("# points\n1 0 0 3 100 100 100 0.1 1 0 2 0\n")


def frame_source(root: Path) -> tuple[FrameSetResolver, ProductArtifactRef]:
    """Versioned fixture inventory đi qua REC-02A resolver thật."""
    root.mkdir(parents=True, exist_ok=True)
    frames = []
    mapping = {}
    for i in range(4):
        path = root / f"{i:06d}.png"
        path.write_bytes(f"fixture frame {i}".encode())
        ref = reference(path.name, path.read_bytes(), "RGBFrame")
        frames.append(
            dict(
                frame_id=i,
                timestamp_sec=str(i),
                image=ref.model_dump(mode="json"),
                source_checksum=ref.artifact_checksum,
            )
        )
        mapping[ref.artifact_uri] = path
    timestamps = hashlib.sha256(json.dumps({str(i): str(i) for i in range(4)}, sort_keys=True).encode()).hexdigest()
    payload = dict(
        schema_version="1.0",
        frames=frames,
        ffmpeg_version="fixture",
        **{
            key: "sha256:" + "a" * 64
            for key in (
                "input_manifest_checksum",
                "quality_report_checksum",
                "privacy_report_checksum",
                "selection_checksum",
                "extraction_config_checksum",
            )
        },
        timestamp_inventory_checksum="sha256:" + timestamps,
    )
    payload["frame_set_checksum"] = "sha256:" + "0" * 64
    payload["frame_set_checksum"] = canonical_content_checksum(payload, "frame_set_checksum")
    data = json.dumps(payload).encode()
    path = root / "frame_set.json"
    path.write_bytes(data)
    ref = reference(path.name, data, "NormalizedRGBFrameSet")
    mapping[ref.artifact_uri] = path
    return FrameSetResolver(lambda r: mapping[r.artifact_uri], lambda r: mapping[r.artifact_uri]), ref


def reference(name: str, data: bytes, kind: str) -> ProductArtifactRef:
    """Checksummed fixture reference với data classification explicit."""
    return ProductArtifactRef(
        artifact_type=kind,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/input/{name}",
        artifact_checksum="sha256:" + hashlib.sha256(data).hexdigest(),
        data_class="derived",
        producer_stage="ST-FRAME-EXTRACT",
    )


class FixtureProcess(ColmapProcess):
    """Mock chỉ orchestration, dùng real parser/storage/resolver cho handoff."""

    def __init__(self, mode: str = "success") -> None:
        super().__init__(ColmapRuntimeSettings(runtime_identity="fixture"))
        self.mode = mode
        self.commands: list[list[str]] = []

    def capabilities(self, workspace: Path) -> tuple[str, str, str]:
        (workspace / "process.log").write_text("fixture COLMAP process\n")
        return "COLMAP fixture", "FeatureExtraction", "FeatureMatching"

    def run(self, arguments: list[str], workspace: Path) -> str:
        self.commands.append(arguments)
        if self.mode == "failed":
            raise ColmapError("COLMAP_PROCESS_FAILED", "fixture process failure")
        if arguments[0] == "mapper" and self.mode != "empty":
            for model in ("0", "2", "10"):
                (workspace / "sparse" / model).mkdir()
        if arguments[0] == "model_converter":
            directory = workspace / arguments[arguments.index("--output_path") + 1]
            sparse(directory, (0, 1) if directory.name == "0" else (0, 1, 2))
        return ""


def adapter(root: Path, mode: str = "success") -> tuple[ColmapAdapter, ColmapRequest, CameraPoseResolver]:
    """Full internal boundary với published fixture input."""
    frames, ref = frame_source(root / "source")
    resolver = ArtifactResolver(root / "store")
    deps = ColmapDependencies(frames, FixtureProcess(mode), FilesystemArtifactStore(resolver), resolver.require)
    return (
        ColmapAdapter(deps),
        ColmapRequest(ref, config(), root / "work", "rec03-fixture"),
        CameraPoseResolver(resolver.require, frames),
    )


def test_largest_model_and_numeric_tie_break(tmp_path: Path) -> None:
    """Model 2/10 cùng size; chọn 2, không model 0 hoặc filesystem ordering."""
    models = []
    for name, ids in (("10", (0, 1, 2)), ("0", (0, 1)), ("2", (0, 1, 2))):
        sparse(tmp_path / name, ids)
        models.append(read_sparse_model(tmp_path / name, (0, 1, 2, 3)))
    assert select_sparse_model(models).stats.model_id == "2"
    assert select_sparse_model(list(reversed(models))).stats.model_id == "2"
    with pytest.raises(ValueError, match="no valid sparse"):
        select_sparse_model([])


def test_pose_inverse_with_rotation_and_translation(tmp_path: Path) -> None:
    """Camera center = -R^T t, không chỉ đảo dấu t hoặc đổi thứ tự quaternion."""
    directory = tmp_path / "0"
    sparse(directory, (0, 1))
    q = math.sqrt(0.5)
    (directory / "images.txt").write_text(f"1 {q} 0 0 {q} 1 2 3 1 000000.png\n\n2 1 0 0 0 0 0 0 1 000001.png\n\n")
    pose = read_sparse_model(directory, (0, 1)).poses[0]
    assert pose.translation == pytest.approx((-2, 1, -3))
    assert pose.rotation_xyzw == pytest.approx((0, 0, -q, q))


@pytest.mark.parametrize(
    "failure", ["missing", "empty", "truncated", "foreign", "duplicate", "nan", "camera", "quaternion", "point"]
)
def test_invalid_sparse_models(tmp_path: Path, failure: str) -> None:
    """Output hỏng không được trở thành successful artifact."""
    directory = tmp_path / "0"
    sparse(directory, (0, 1))
    image_path = directory / "images.txt"
    text = image_path.read_text()
    if failure == "missing":
        (directory / "cameras.txt").unlink()
    elif failure == "empty":
        (directory / "points3D.txt").write_text("# no points\n")
    elif failure == "truncated":
        image_path.write_text(text.rstrip())
    elif failure in {"foreign", "duplicate"}:
        image_path.write_text(text.replace("000001.png", "000009.png" if failure == "foreign" else "000000.png"))
    elif failure == "nan":
        image_path.write_text(text.replace("1 1 0 0 0 0", "1 1 0 0 0 nan"))
    elif failure == "camera":
        (directory / "cameras.txt").write_text("1 PINHOLE 640 480 400 400 320\n")
    elif failure == "quaternion":
        image_path.write_text(text.replace("1 1 0 0 0", "1 2 0 0 0"))
    elif failure == "point":
        (directory / "points3D.txt").write_text("1 nan 0 3 0 0 0 0.1 1 0\n")
    with pytest.raises((ValueError, OSError)):
        read_sparse_model(directory, (0, 1))


@pytest.mark.parametrize("prefixes", [("FeatureExtraction", "FeatureMatching"), ("SiftExtraction", "SiftMatching")])
def test_command_flags_and_explicit_config(prefixes: tuple[str, str]) -> None:
    """CLI generation support qualified old/new flag namespaces."""
    commands = reconstruction_commands(config(), prefixes)
    assert [command[0] for command in commands] == ["feature_extractor", "sequential_matcher", "mapper"]
    assert f"--{prefixes[0]}.use_gpu" in commands[0]
    assert f"--{prefixes[1]}.use_gpu" in commands[1]
    assert commands[1][commands[1].index("--SequentialMatching.loop_detection") + 1] == "0"
    assert "--SequentialMatching.vocab_tree_path" not in commands[1]
    assert commands[2][commands[2].index("--Mapper.random_seed") + 1] == str(config().random_seed)
    with pytest.raises(ValueError):
        config(min_registered_ratio=0)


def test_published_handoff_and_immutable_sources(tmp_path: Path) -> None:
    """REC-04/05 đọc selected sparse từ artifact, không qua workspace riêng."""
    service, request, resolver = adapter(tmp_path)
    result = service.execute(request)
    artifact = resolver.load(result.reference)
    assert result.stage.status.value == "SUCCEEDED"
    assert artifact.selected_model_id == "2"
    assert artifact.registered_ratio == 0.75
    assert artifact.unregistered_frame_ids == [3]
    assert artifact.scale_status == "arbitrary_sfm"
    assert artifact.world_alignment_status == "unconfirmed"
    target = resolver.materialize_sparse(artifact, tmp_path / "consumer")
    assert read_sparse_model(target.rename(tmp_path / "20"), (0, 1, 2, 3)).stats.registered_frames == 3
    (request.workspace / "text/2/images.txt").write_text("changed temp file")
    assert resolver.load(result.reference) == artifact
    with pytest.raises(ColmapError):
        service.execute(request)
    resolver.require(artifact.sparse_files["images.txt"]).write_text("tampered")
    with pytest.raises(ArtifactChecksumError):
        resolver.load(result.reference)


@pytest.mark.parametrize("mode", ["failed", "empty", "threshold"])
def test_failure_does_not_publish_manifest(tmp_path: Path, mode: str) -> None:
    """Lỗi process/no-model/registration trả failed stage, không publish success manifest."""
    service, request, _ = adapter(tmp_path, mode)
    if mode == "threshold":
        request = ColmapRequest(request.frame_set, config(min_registered_ratio=1), request.workspace, request.job_id)
    with pytest.raises(ColmapError) as error:
        service.execute(request)
    assert error.value.to_failed_stage().status.value == "FAILED"
    assert not list((tmp_path / "store").rglob("camera_poses.json"))


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing"])
def test_real_process_boundary_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    """Mock subprocess OS outcomes; prove adapter never swallows failure."""

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        if failure == "timeout":
            raise subprocess.TimeoutExpired("colmap", 1)
        if failure == "missing":
            raise FileNotFoundError("private runtime path")
        return subprocess.CompletedProcess(args, 7)

    monkeypatch.setattr(subprocess, "run", run)
    process = ColmapProcess(ColmapRuntimeSettings(runtime_identity="fixture"))
    with pytest.raises(ColmapError) as error:
        process.run(["mapper"], tmp_path)
    assert "private runtime path" not in str(error.value)
    assert (tmp_path / "process.log").is_file()


def test_content_and_provenance_integrity(tmp_path: Path) -> None:
    """Rehash alone cannot hide inconsistent stats or wrong input frame lineage."""
    service, request, _ = adapter(tmp_path)
    artifact = service.execute(request).artifact
    payload = artifact.model_dump(mode="json")
    payload["registered_ratio"] = 1.0
    payload["artifact_checksum"] = canonical_content_checksum(payload, "artifact_checksum")
    with pytest.raises(ValueError, match="ratio mismatch"):
        CameraPoseArtifact.model_validate(payload)
    payload = artifact.model_dump(mode="json")
    payload["config"]["random_seed"] = 99
    payload["artifact_checksum"] = canonical_content_checksum(payload, "artifact_checksum")
    with pytest.raises(ValueError, match="config checksum"):
        CameraPoseArtifact.model_validate(payload)


def test_vocab_checksum_is_verified_before_process(tmp_path: Path) -> None:
    """Optional vocabulary is explicit checksummed input; no implicit download."""
    service, request, _ = adapter(tmp_path)
    vocab = reference("vocab.bin", b"missing vocab", "VocabularyTree")
    request = ColmapRequest(request.frame_set, config(vocab_tree=vocab.model_dump()), request.workspace, request.job_id)
    with pytest.raises(ColmapError):
        service.execute(request)
    assert service.deps.process.commands == []


@pytest.mark.parametrize("modern", [True, False])
def test_capability_detection_uses_actual_help(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, modern: bool) -> None:
    """Namespace dựa trên binary help, không dựa trên local source version."""
    extraction = "FeatureExtraction" if modern else "SiftExtraction"
    matching = "FeatureMatching" if modern else "SiftMatching"
    output = {
        "-h": "COLMAP 3.9 fixture",
        "feature_extractor": f"--{extraction}.use_gpu",
        "sequential_matcher": f"--{matching}.use_gpu",
    }
    process = ColmapProcess(ColmapRuntimeSettings(runtime_identity="fixture"))
    monkeypatch.setattr(process, "run", lambda args, workspace: output[args[0]])
    assert process.capabilities(tmp_path) == ("COLMAP 3.9 fixture", extraction, matching)


def test_unknown_runtime_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown tool/version không được tự gán known COLMAP provenance."""
    process = ColmapProcess(ColmapRuntimeSettings(runtime_identity="fixture"))
    monkeypatch.setattr(process, "run", lambda args, workspace: "other executable")
    with pytest.raises(ColmapError, match="version"):
        process.capabilities(tmp_path)


def test_invalid_source_checksum_stops_before_sfm(tmp_path: Path) -> None:
    """Source đã đổi sau REC-02A phải bị chặn trước heavy tool."""
    service, request, _ = adapter(tmp_path)
    (tmp_path / "source/000001.png").write_bytes(b"changed upstream")
    with pytest.raises(ColmapError):
        service.execute(request)
    assert service.deps.process.commands == []
    assert not list((tmp_path / "store").rglob("camera_poses.json"))


def test_missing_registration_policy_is_rejected() -> None:
    """Không default âm thầm tỷ lệ đủ tốt cho product/demo."""
    payload = config().model_dump()
    del payload["min_registered_ratio"]
    with pytest.raises(ValueError, match="min_registered_ratio"):
        ColmapConfig.model_validate(payload)
