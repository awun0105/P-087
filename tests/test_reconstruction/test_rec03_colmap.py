"""REC-03 unit/fixture proof; actual COLMAP smoke có evidence riêng."""

import hashlib
import json
import math
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.services.orchestration.artifacts.errors import ArtifactChecksumError
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.process_control import ProcessTimeoutError
from src.services.reconstruction.adapters import colmap_runtime
from src.services.reconstruction.adapters.colmap import ColmapAdapter, ColmapDependencies, ColmapRequest
from src.services.reconstruction.adapters.colmap_model import read_sparse_model, select_sparse_model
from src.services.reconstruction.adapters.colmap_runtime import (
    ColmapError,
    ColmapProcess,
    ColmapRuntimeSettings,
    reconstruction_commands,
)
from src.services.reconstruction.resume import ResumeCache
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
            output = arguments[arguments.index("--output_path") + 1] if "--output_path" in arguments else "sparse"
            for model in ("0", "2", "10"):
                directory = workspace / output / model
                directory.mkdir()
                (directory / "points3D.bin").write_bytes(f"fixture sparse model {model}".encode())
        if arguments[0] == "model_converter":
            directory = workspace / arguments[arguments.index("--output_path") + 1]
            sparse(directory, (0, 1) if directory.name == "0" else (0, 1, 2))
        return ""


def adapter(
    root: Path, mode: str = "success", resume: ResumeCache | None = None, attempt_id: str | None = None
) -> tuple[ColmapAdapter, ColmapRequest, CameraPoseResolver]:
    """Full internal boundary với published fixture input."""
    frames, ref = frame_source(root / "source")
    resolver = ArtifactResolver(root / "store")
    deps = ColmapDependencies(frames, FixtureProcess(mode), FilesystemArtifactStore(resolver), resolver.require, resume)
    return (
        ColmapAdapter(deps),
        ColmapRequest(ref, config(), root / "work", "rec03-fixture", attempt_id),
        CameraPoseResolver(resolver.require, frames),
    )


def test_model_image_format_must_match_staged_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Accepting JPEG must not allow a sparse model to name absent images for PNG inputs."""
    service, request, _ = adapter(tmp_path)
    original = service.deps.process.run

    def mismatched_names(arguments: list[str], workspace: Path) -> str:
        result = original(arguments, workspace)
        if arguments[0] == "model_converter":
            path = workspace / arguments[arguments.index("--output_path") + 1] / "images.txt"
            path.write_text(path.read_text().replace(".png", ".jpg"))
        return result

    monkeypatch.setattr(service.deps.process, "run", mismatched_names)
    with pytest.raises(ColmapError) as error:
        service.execute(request)
    assert error.value.code == "COLMAP_ARTIFACT_INVALID"
    assert not list((tmp_path / "store").rglob("camera_poses.json"))


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


def test_colmap_use_gpu_command_flags() -> None:
    gpu_cfg = config(use_gpu=True)
    prefixes = ("SiftExtraction", "SiftMatching")
    commands = reconstruction_commands(gpu_cfg, prefixes)
    assert [command[0] for command in commands] == ["feature_extractor", "sequential_matcher", "mapper"]
    # feature_extractor có "1" ngay sau --SiftExtraction.use_gpu
    fe_cmd = commands[0]
    assert fe_cmd[fe_cmd.index(f"--{prefixes[0]}.use_gpu") + 1] == "1"
    # sequential_matcher có "1" ngay sau --SiftMatching.use_gpu
    sm_cmd = commands[1]
    assert sm_cmd[sm_cmd.index(f"--{prefixes[1]}.use_gpu") + 1] == "1"
    # mapper không chứa cờ use_gpu
    mapper_cmd = commands[2]
    assert not any("use_gpu" in arg for arg in mapper_cmd)


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


def test_resume_cache_reuses_verified_colmap_and_recovers_from_corruption(tmp_path: Path) -> None:
    resume = ResumeCache(tmp_path / "resume")
    cold, cold_request, _ = adapter(tmp_path / "cold", resume=resume, attempt_id="cold")
    cold_result = cold.execute(cold_request)
    cold_checksums = {name: ref.artifact_checksum for name, ref in cold_result.artifact.sparse_files.items()}
    assert any(command[0] == "mapper" for command in cold.deps.process.commands)

    warm, warm_request, _ = adapter(tmp_path / "warm", resume=ResumeCache(tmp_path / "resume"), attempt_id="warm")
    warm_result = warm.execute(warm_request)
    assert not any(
        command[0] in {"feature_extractor", "sequential_matcher", "mapper"} for command in warm.deps.process.commands
    )
    assert warm_result.artifact.poses == cold_result.artifact.poses
    assert {name: ref.artifact_checksum for name, ref in warm_result.artifact.sparse_files.items()} == cold_checksums

    assert cold_result.resume_key is not None
    cached_points = resume._colmap(cold_result.resume_key) / "sparse/2/points3D.bin"
    original = cached_points.read_bytes()
    cached_points.write_bytes(bytes([original[0] ^ 1]) + original[1:])

    recovered, recovered_request, _ = adapter(tmp_path / "recovered", resume=resume, attempt_id="recovered")
    recovered_result = recovered.execute(recovered_request)
    assert any(command[0] == "mapper" for command in recovered.deps.process.commands)
    assert recovered_result.artifact.poses == cold_result.artifact.poses
    assert {
        name: ref.artifact_checksum for name, ref in recovered_result.artifact.sparse_files.items()
    } == cold_checksums
    assert list((tmp_path / "resume").glob(f".invalid-colmap-{cold_result.resume_key}-*"))

    repaired, repaired_request, _ = adapter(tmp_path / "repaired", resume=resume, attempt_id="repaired")
    repaired.execute(repaired_request)
    assert not any(
        command[0] in {"feature_extractor", "sequential_matcher", "mapper"}
        for command in repaired.deps.process.commands
    )


def test_resume_store_failure_does_not_discard_verified_pose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    resume = ResumeCache(tmp_path / "resume")

    def fail_store(key: str, workspace: Path) -> None:
        raise OSError("cache disk unavailable")

    monkeypatch.setattr(resume, "store_colmap", fail_store)
    service, request, resolver = adapter(tmp_path, resume=resume)
    result = service.execute(request)

    assert result.stage.status.value == "SUCCEEDED"
    assert resolver.load(result.reference) == result.artifact


def test_resume_restore_failure_falls_back_to_cold_colmap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    resume = ResumeCache(tmp_path / "resume")

    def fail_restore(_key: str, _workspace: Path) -> bool:
        raise OSError("cache disk unavailable")

    monkeypatch.setattr(resume, "restore_colmap", fail_restore)
    service, request, resolver = adapter(tmp_path, resume=resume)
    result = service.execute(request)

    assert any(command[0] == "mapper" for command in service.deps.process.commands)
    assert result.stage.status.value == "SUCCEEDED"
    assert resolver.load(result.reference) == result.artifact


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

    def run(*args: object, **kwargs: object) -> int:
        if failure == "timeout":
            raise ProcessTimeoutError("colmap")
        if failure == "missing":
            raise FileNotFoundError("private runtime path")
        return 7

    monkeypatch.setattr(colmap_runtime, "_run_watched", run)
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


def test_redacted_excerpt(tmp_path: Path) -> None:
    from src.services.reconstruction.adapters.log_excerpt import redacted_excerpt

    ws = tmp_path / "work"
    ws.mkdir()
    raw = f"Processing in {ws}/input\nError calling /usr/bin/colmap at /opt/tools/bin\nDone\n"
    res = redacted_excerpt(raw, ws)
    assert res == ["Processing in <workspace>/input", "Error calling <path> at <path>", "Done"]
    assert redacted_excerpt("", ws) == []

    # Test max_lines and max_bytes
    many_lines = "\n".join(f"line {i}" for i in range(100))
    res_lines = redacted_excerpt(many_lines, ws, max_lines=5)
    assert len(res_lines) == 5
    assert res_lines[-1] == "line 99"

    res_bytes = redacted_excerpt(many_lines, ws, max_lines=5, max_bytes=20)
    assert sum(len(line.encode("utf-8")) for line in res_bytes) <= 20


def test_colmap_process_exit_codes_and_oom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.models.contracts.retryability import classify_retryability

    # 1. Sequential commands: log_excerpt only contains second command log
    process = ColmapProcess(ColmapRuntimeSettings(runtime_identity="fixture"))
    log_file = tmp_path / "process.log"

    def run_first(*args: object, **kwargs: object) -> int:
        with log_file.open("a") as f:
            f.write("first command output\n")
        return 0

    monkeypatch.setattr(colmap_runtime, "_run_watched", run_first)
    process.run(["feature_extractor"], tmp_path)

    def run_second(*args: object, **kwargs: object) -> int:
        with log_file.open("a") as f:
            f.write(f"second command failed in {tmp_path}/data\n")
        return 7

    monkeypatch.setattr(colmap_runtime, "_run_watched", run_second)
    with pytest.raises(ColmapError) as exc_info:
        process.run(["exhaustive_matcher"], tmp_path)

    err = exc_info.value
    assert err.code == "COLMAP_PROCESS_FAILED"
    stage = err.to_failed_stage()
    assert stage.error is not None
    assert "log_excerpt" in stage.error.details
    excerpt = stage.error.details["log_excerpt"]
    assert any("second command failed in <workspace>/data" in line for line in excerpt)
    assert not any("first command output" in line for line in excerpt)
    assert str(tmp_path) not in str(stage.error.details)

    # 2. Exit -9 and 137 -> COLMAP_OUT_OF_MEMORY
    for code in (-9, 137):
        monkeypatch.setattr(colmap_runtime, "_run_watched", lambda *args, **kwargs: code)
        with pytest.raises(ColmapError) as oom_info:
            process.run(["mapper"], tmp_path)
        assert oom_info.value.code == "COLMAP_OUT_OF_MEMORY"
        failed = oom_info.value.to_failed_stage()
        assert failed.error is not None
        assert failed.error.retryable is True
        assert classify_retryability("COLMAP_OUT_OF_MEMORY") is True

    # 3. std::bad_alloc with exit 1 -> COLMAP_OUT_OF_MEMORY
    def run_bad_alloc(*args: object, **kwargs: object) -> int:
        with log_file.open("a") as f:
            f.write("terminate called after throwing an instance of 'std::bad_alloc'\n")
        return 1

    monkeypatch.setattr(colmap_runtime, "_run_watched", run_bad_alloc)
    with pytest.raises(ColmapError) as alloc_info:
        process.run(["mapper"], tmp_path)
    assert alloc_info.value.code == "COLMAP_OUT_OF_MEMORY"


def test_colmap_no_model_diagnostics(tmp_path: Path) -> None:
    service, request, _ = adapter(tmp_path)
    orig_run = service.deps.process.run

    def mock_run(arguments: list[str], workspace: Path) -> str:
        if arguments[0] == "mapper":
            with (workspace / "process.log").open("a") as f:
                f.write(
                    "Discarding reconstruction due to no initial pair\n"
                    "Discarding reconstruction due to no initial pair\n"
                    "Discarding reconstruction due to insufficient size\n"
                )
        return orig_run(arguments, workspace)

    service.deps.process.run = mock_run  # type: ignore[method-assign]
    service._models = lambda ws, ids, **_: []  # type: ignore[assignment]

    with pytest.raises(ColmapError) as no_model_info:
        service.execute(request)

    err = no_model_info.value
    assert err.code == "COLMAP_NO_MODEL"
    stage = err.to_failed_stage()
    assert stage.error is not None
    assert stage.error.retryable is False
    # Ba lần `mapper` (lần đầu + hai bậc thử lại) cùng ghi vào process.log.
    assert stage.error.details["diagnostics"] == {"no_initial_pair": 6, "insufficient_size": 3}
    assert "log_excerpt" in stage.error.details
    assert str(tmp_path) not in str(stage.error.details)
    # Thang thử lại đã chạy đủ hai bậc trước khi báo lỗi (T-071 C3).
    assert [item["step"] for item in stage.error.details["retry_ladder"]] == [1, 2]


def test_colmap_registration_low_details(tmp_path: Path) -> None:
    service, request, _ = adapter(tmp_path)
    request = ColmapRequest(
        request.frame_set,
        config(min_registered_ratio=1.0, min_registered_frames=100),
        request.workspace,
        request.job_id,
    )
    with pytest.raises(ColmapError) as low_info:
        service.execute(request)

    assert low_info.value.code == "COLMAP_REGISTRATION_LOW"
    stage = low_info.value.to_failed_stage()
    assert stage.error is not None
    assert "registered_frames" in stage.error.details
    assert "input_frames" in stage.error.details
    assert "min_registered_ratio" in stage.error.details
    assert stage.error.details["registered_frames"] == 3
    assert stage.error.details["input_frames"] == 4
    assert stage.error.details["min_registered_ratio"] == 1.0
    assert stage.error.details["retry_ladder"] == [
        {"step": 1, "matching_mode": "sequential", "overlap": 10, "registered_frames": 3, "input_frames": 4},
        {"step": 2, "matching_mode": "exhaustive", "overlap": None, "registered_frames": 3, "input_frames": 4},
    ]


def test_excerpt_keeps_tail_of_a_single_oversized_line_and_slices_log_by_bytes(tmp_path: Path) -> None:
    from src.services.reconstruction.adapters.colmap_runtime import _log_since
    from src.services.reconstruction.adapters.log_excerpt import redacted_excerpt

    excerpt = redacted_excerpt("x" * 5000 + "END", tmp_path, max_bytes=100)
    assert len(excerpt) == 1 and excerpt[0].endswith("END") and len(excerpt[0].encode()) <= 100

    log = tmp_path / "process.log"
    log.write_text("lệnh trước: đã xong\n", encoding="utf-8")
    offset = log.stat().st_size
    with log.open("a", encoding="utf-8") as handle:
        handle.write("lệnh sau: lỗi\n")
    assert _log_since(log, offset) == "lệnh sau: lỗi\n"
    assert _log_since(tmp_path / "missing.log", 0) == ""
