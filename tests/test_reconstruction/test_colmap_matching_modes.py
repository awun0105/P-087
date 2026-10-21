import hashlib
import struct
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.identity import canonical_json_bytes
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.adapters.colmap import ColmapAdapter, ColmapDependencies, ColmapRequest
from src.services.reconstruction.adapters.colmap_runtime import (
    ColmapError,
    ColmapProcess,
    ColmapRuntimeSettings,
    reconstruction_commands,
)
from src.services.reconstruction.resume import ResumeCache
from src.services.reconstruction.rgb.pose.camera_pose import ColmapConfig
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from tests.test_reconstruction.test_rec03_colmap import FixtureProcess, adapter, config, frame_source, sparse


@pytest.mark.parametrize("match", ["SiftMatching", "FeatureMatching"])
@pytest.mark.parametrize("mode", ["sequential", "sequential_vocab_tree", "exhaustive"])
def test_matching_modes_have_their_own_commands(mode: str, match: str) -> None:
    cfg = config(
        matching_mode=mode,
        use_gpu=True,
        loop_detection_period=7,
        loop_detection_num_images=33,
        loop_detection_min_index_distance=20,
    )
    command = reconstruction_commands(cfg, ("FeatureExtraction", match))[1]
    assert command[command.index(f"--{match}.use_gpu") + 1] == "1"
    assert command[command.index(f"--{match}.num_threads") + 1] == "2"
    if mode == "exhaustive":
        assert command[0] == "exhaustive_matcher"
        assert not any("SequentialMatching" in item for item in command)
    else:
        assert command[0] == "sequential_matcher"
        assert command[command.index("--SequentialMatching.overlap") + 1] == "5"
        assert command[command.index("--SequentialMatching.loop_detection") + 1] == str(
            int(mode == "sequential_vocab_tree")
        )
        if mode == "sequential_vocab_tree":
            assert command[command.index("--SequentialMatching.vocab_tree_path") + 1] == "vocab_tree.bin"
            for key, value in [("period", "7"), ("num_images", "33"), ("min_index_distance", "20")]:
                assert command[command.index(f"--SequentialMatching.loop_detection_{key}") + 1] == value
        else:
            assert "--SequentialMatching.vocab_tree_path" not in command


def test_old_config_bytes_stay_stable_but_mode_and_loop_tuning_change_identity() -> None:
    old = dict(
        schema_version="1.0",
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
        vocab_tree=None,
    )
    assert config().model_dump(mode="json") == old
    assert config().checksum() == "sha256:" + hashlib.sha256(canonical_json_bytes(old)).hexdigest()
    assert config().checksum() != config(matching_mode="exhaustive").checksum()
    assert config().checksum() != config(loop_detection_period=9).checksum()


@pytest.mark.parametrize(
    "changes",
    [
        {"matching_mode": "spatial"},
        {"loop_detection_period": 0},
        {"loop_detection_num_images": 0},
        {"loop_detection_min_index_distance": -1},
    ],
)
def test_invalid_mode_or_loop_limits_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        config(**changes)


@pytest.mark.parametrize("mode", ["sequential_vocab_tree", "exhaustive"])
def test_actual_mode_help_is_probed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    calls: list[str] = []

    def run(arguments: list[str], workspace: Path) -> str:
        calls.append(arguments[0])
        if arguments[0] == "-h":
            return "COLMAP 4.3.0"
        if arguments[0] == "feature_extractor":
            return "--FeatureExtraction.use_gpu"
        return "--FeatureMatching.use_gpu " + " ".join(
            f"--SequentialMatching.{name}"
            for name in [
                "loop_detection",
                "vocab_tree_path",
                "loop_detection_period",
                "loop_detection_num_images",
                "loop_detection_min_index_distance",
            ]
        )

    process = ColmapProcess(ColmapRuntimeSettings(runtime_identity="fixture"))
    monkeypatch.setattr(process, "run", run)
    assert process.capabilities(tmp_path, mode) == ("COLMAP 4.3.0", "FeatureExtraction", "FeatureMatching")
    assert calls[-1] == ("exhaustive_matcher" if mode == "exhaustive" else "sequential_matcher")


def test_loop_controls_missing_from_binary_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = ColmapProcess(ColmapRuntimeSettings(runtime_identity="fixture"))
    output = {
        "-h": "COLMAP 4.3.0",
        "feature_extractor": "--FeatureExtraction.use_gpu",
        "sequential_matcher": "--FeatureMatching.use_gpu",
    }
    monkeypatch.setattr(process, "run", lambda arguments, workspace: output[arguments[0]])
    with pytest.raises(ColmapError, match="loop controls"):
        process.capabilities(tmp_path, "sequential_vocab_tree")


def test_missing_vocabulary_stops_before_matching(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, request, _ = adapter(tmp_path)
    monkeypatch.setattr(
        service.deps.process,
        "capabilities",
        lambda workspace, mode: ("COLMAP 4.3.0", "FeatureExtraction", "FeatureMatching"),
    )
    monkeypatch.setattr("src.services.reconstruction.adapters.colmap.get_vocab_tree_path", lambda **kwargs: None)
    with pytest.raises(ColmapError) as error:
        service.execute(
            ColmapRequest(
                request.frame_set, config(matching_mode="sequential_vocab_tree"), request.workspace, request.job_id
            )
        )
    assert error.value.code == "VOCAB_TREE_MISSING"
    assert "--format faiss" in error.value.details["action"]
    assert service.deps.process.commands == []


@pytest.mark.parametrize("modern", [False, True])
def test_adapter_stages_the_matching_vocabulary_and_runs_loop_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, modern: bool
) -> None:
    service, request, resolver = adapter(tmp_path)
    version = "COLMAP 4.3.0" if modern else "COLMAP 3.9.0"
    original_probe = service.deps.process.capabilities

    def probe(workspace: Path, mode: str) -> tuple[str, str, str]:
        original_probe(workspace)
        return version, "FeatureExtraction", "FeatureMatching"

    monkeypatch.setattr(service.deps.process, "capabilities", probe)
    tree = tmp_path / "tree.bin"
    tree.write_bytes(struct.pack("<i", 1 if modern else 262144) + b"fixture vocabulary")
    formats: list[str] = []

    def find(*, format: str) -> Path:
        formats.append(format)
        return tree

    monkeypatch.setattr("src.services.reconstruction.adapters.colmap.get_vocab_tree_path", find)
    result = service.execute(
        ColmapRequest(
            request.frame_set, config(matching_mode="sequential_vocab_tree"), request.workspace, request.job_id
        )
    )
    assert formats == ["faiss" if modern else "flann"]
    assert (request.workspace / "vocab_tree.bin").read_bytes() == tree.read_bytes()
    assert any(
        command[0] == "sequential_matcher" and command[command.index("--SequentialMatching.loop_detection") + 1] == "1"
        for command in service.deps.process.commands
    )
    assert resolver.load(result.reference).config.matching_mode == "sequential_vocab_tree"


def test_adapter_runs_exhaustive_matching_and_publishes_that_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, request, resolver = adapter(tmp_path)
    original_probe = service.deps.process.capabilities
    monkeypatch.setattr(service.deps.process, "capabilities", lambda workspace, mode: original_probe(workspace))
    result = service.execute(
        ColmapRequest(request.frame_set, config(matching_mode="exhaustive"), request.workspace, request.job_id)
    )
    assert any(command[0] == "exhaustive_matcher" for command in service.deps.process.commands)
    assert not any(command[0] == "sequential_matcher" for command in service.deps.process.commands)
    assert resolver.load(result.reference).config.matching_mode == "exhaustive"


def test_incompatible_tree_does_not_reach_matching(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, request, _ = adapter(tmp_path)
    monkeypatch.setattr(
        service.deps.process,
        "capabilities",
        lambda workspace, mode: ("COLMAP 4.3.0", "FeatureExtraction", "FeatureMatching"),
    )
    tree = tmp_path / "legacy.bin"
    tree.write_bytes(struct.pack("<i", 262144))
    monkeypatch.setattr("src.services.reconstruction.adapters.colmap.get_vocab_tree_path", lambda **kwargs: tree)
    with pytest.raises(ColmapError) as error:
        service.execute(
            ColmapRequest(
                request.frame_set, config(matching_mode="sequential_vocab_tree"), request.workspace, request.job_id
            )
        )
    assert error.value.code == "VOCAB_TREE_INCOMPATIBLE"
    assert service.deps.process.commands == []


# --- T-071 C: thang thử lại COLMAP trong cùng lượt chạy -------------------------------------------------------------

LOOP_HELP = "--FeatureMatching.use_gpu " + " ".join(
    f"--SequentialMatching.{flag}"
    for flag in (
        "loop_detection",
        "vocab_tree_path",
        "loop_detection_period",
        "loop_detection_num_images",
        "loop_detection_min_index_distance",
    )
)


class LadderProcess(FixtureProcess):
    """`mapper` ghi mô hình theo `--output_path`; mỗi thư mục sparse có một kết quả do test chọn."""

    def __init__(
        self, outcomes: dict[str, tuple[int, ...] | None], *, version: str = "COLMAP fixture", help_text: str = ""
    ) -> None:
        super().__init__()
        self.outcomes = outcomes
        self.version = version
        self.help_text = help_text

    def capabilities(self, workspace: Path, mode: str = "sequential") -> tuple[str, str, str]:
        super().capabilities(workspace)
        return self.version, "FeatureExtraction", "FeatureMatching"

    def run(self, arguments: list[str], workspace: Path) -> str:
        self.commands.append(arguments)
        if arguments == ["sequential_matcher", "-h"]:
            return self.help_text
        if arguments[0] == "mapper":
            output = arguments[arguments.index("--output_path") + 1]
            if self.outcomes.get(output) is not None:
                directory = workspace / output / "0"
                directory.mkdir(parents=True)
                (directory / "points3D.bin").write_bytes(f"model {output}".encode())
        if arguments[0] == "model_converter":
            source = arguments[arguments.index("--input_path") + 1].split("/")[0]
            ids = self.outcomes[source]
            assert ids is not None
            sparse(workspace / arguments[arguments.index("--output_path") + 1], ids)
        return ""


def ladder_adapter(
    root: Path, process: LadderProcess, cfg: ColmapConfig | None = None, resume: ResumeCache | None = None
) -> tuple[ColmapAdapter, ColmapRequest, CameraPoseResolver]:
    frames, ref = frame_source(root / "source")
    resolver = ArtifactResolver(root / "store")
    deps = ColmapDependencies(frames, process, FilesystemArtifactStore(resolver), resolver.require, resume)
    request = ColmapRequest(ref, cfg or config(), root / "work", "rec03-ladder")
    return ColmapAdapter(deps), request, CameraPoseResolver(resolver.require, frames)


def _matchers(process: LadderProcess) -> list[list[str]]:
    return [command for command in process.commands if command[0].endswith("_matcher") and command[1:] != ["-h"]]


def test_first_step_runs_when_mapper_finds_no_model_and_stops_at_first_success(tmp_path: Path) -> None:
    process = LadderProcess({"sparse": None, "sparse_r1": (0, 1, 2), "sparse_r2": (0, 1, 2, 3)})
    service, request, resolver = ladder_adapter(tmp_path, process)
    result = service.execute(request)
    matchers = _matchers(process)
    assert [command[0] for command in matchers] == ["sequential_matcher", "sequential_matcher"]
    retry = matchers[1]
    assert retry[retry.index("--SequentialMatching.overlap") + 1] == "10"  # 5 × 2
    assert retry[retry.index("--SequentialMatching.loop_detection") + 1] == "0"  # fixture không có từ điển
    assert [command[-5] for command in process.commands if command[0] == "mapper"] == ["sparse", "sparse_r1"]
    # Không trích đặc trưng lại: chỉ một feature_extractor cho cả lượt.
    assert sum(command[0] == "feature_extractor" for command in process.commands) == 1
    artifact = resolver.load(result.reference)
    assert [step.model_dump() for step in artifact.retry_ladder] == [
        {"step": 1, "matching_mode": "sequential", "overlap": 10, "registered_frames": 3, "input_frames": 4}
    ]
    assert artifact.registered_ratio == 0.75 and not artifact.registration_warning
    # Bậc thành công đã thành `sparse/`; mô hình hỏng của lần đầu nằm ở `sparse_r0/`.
    assert (request.workspace / "sparse/0/points3D.bin").read_bytes() == b"model sparse_r1"
    assert (request.workspace / "sparse_r0").is_dir()


def test_exhaustive_step_runs_only_for_small_frame_sets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes: dict[str, tuple[int, ...] | None] = {"sparse": None, "sparse_r1": None, "sparse_r2": (0, 1, 2)}
    process = LadderProcess(dict(outcomes))
    service, request, resolver = ladder_adapter(tmp_path / "small", process)
    artifact = resolver.load(service.execute(request).reference)
    assert [command[0] for command in _matchers(process)][-1] == "exhaustive_matcher"
    assert [step.matching_mode for step in artifact.retry_ladder] == ["sequential", "exhaustive"]
    assert artifact.retry_ladder[1].overlap is None

    monkeypatch.setattr("src.services.reconstruction.adapters.colmap.EXHAUSTIVE_RETRY_MAX_IMAGES", 3)
    large = LadderProcess(dict(outcomes))
    service, request, _ = ladder_adapter(tmp_path / "large", large)
    with pytest.raises(ColmapError) as error:
        service.execute(request)
    assert error.value.code == "COLMAP_NO_MODEL"
    assert not any(command[0] == "exhaustive_matcher" for command in large.commands)
    assert [item["step"] for item in error.value.details["retry_ladder"]] == [1]


def test_first_step_enables_loop_detection_only_when_the_worker_has_the_vocabulary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "tree.bin"
    tree.write_bytes(struct.pack("<i", 1) + b"faiss fixture")
    monkeypatch.setattr("src.services.reconstruction.adapters.colmap.get_vocab_tree_path", lambda **kwargs: tree)
    outcomes = {"sparse": None, "sparse_r1": (0, 1, 2)}
    process = LadderProcess(dict(outcomes), version="COLMAP 4.3.0", help_text=LOOP_HELP)
    service, request, resolver = ladder_adapter(tmp_path / "with", process)
    artifact = resolver.load(service.execute(request).reference)
    retry = _matchers(process)[1]
    assert retry[retry.index("--SequentialMatching.loop_detection") + 1] == "1"
    assert retry[retry.index("--SequentialMatching.vocab_tree_path") + 1] == "vocab_tree.bin"
    assert (request.workspace / "vocab_tree.bin").read_bytes() == tree.read_bytes()
    assert artifact.retry_ladder[0].matching_mode == "sequential_vocab_tree"
    assert artifact.config.matching_mode == "sequential"  # config của job không đổi

    monkeypatch.setattr("src.services.reconstruction.adapters.colmap.get_vocab_tree_path", lambda **kwargs: None)
    missing = LadderProcess(dict(outcomes), version="COLMAP 4.3.0", help_text=LOOP_HELP)
    service, request, resolver = ladder_adapter(tmp_path / "without", missing)
    artifact = resolver.load(service.execute(request).reference)  # thiếu từ điển không ném VOCAB_TREE_MISSING
    retry = _matchers(missing)[1]
    assert retry[retry.index("--SequentialMatching.loop_detection") + 1] == "0"
    assert "--SequentialMatching.vocab_tree_path" not in retry
    assert artifact.retry_ladder[0].matching_mode == "sequential"


def test_loop_config_doubles_overlap_and_exhaustive_config_has_no_ladder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "tree.bin"
    tree.write_bytes(struct.pack("<i", 1) + b"faiss fixture")
    monkeypatch.setattr("src.services.reconstruction.adapters.colmap.get_vocab_tree_path", lambda **kwargs: tree)
    process = LadderProcess({"sparse": None, "sparse_r1": (0, 1, 2)}, version="COLMAP 4.3.0", help_text=LOOP_HELP)
    service, request, _ = ladder_adapter(
        tmp_path / "loop", process, config(matching_mode="sequential_vocab_tree", sequential_overlap=20)
    )
    service.execute(request)
    retry = _matchers(process)[1]
    assert retry[retry.index("--SequentialMatching.overlap") + 1] == "30"  # min(30, 20 × 2)
    assert retry[retry.index("--SequentialMatching.loop_detection") + 1] == "1"

    exhaustive = LadderProcess({"sparse": None})
    service, request, _ = ladder_adapter(tmp_path / "exhaustive", exhaustive, config(matching_mode="exhaustive"))
    with pytest.raises(ColmapError) as error:
        service.execute(request)
    assert error.value.code == "COLMAP_NO_MODEL" and "retry_ladder" not in error.value.details
    assert sum(command[0] == "mapper" for command in exhaustive.commands) == 1


def test_low_registration_after_ladder_is_accepted_with_a_warning_above_the_retry_gate(tmp_path: Path) -> None:
    """C3: ≥ 35% ảnh (và ≥ min_registered_frames) sau thang → nhận kèm cảnh báo; dưới 35% vẫn lỗi."""
    process = LadderProcess({"sparse": (0, 1), "sparse_r1": (0, 1), "sparse_r2": (0, 1)})
    cfg = config(min_registered_ratio=0.75, accept_registered_ratio_after_retry=0.35)
    service, request, resolver = ladder_adapter(tmp_path / "accepted", process, cfg)
    artifact = resolver.load(service.execute(request).reference)
    assert artifact.registration_warning is True
    assert artifact.registered_ratio == 0.5
    assert [step.step for step in artifact.retry_ladder] == [1, 2]
    # Không bậc nào tốt hơn: giữ mô hình của lần đầu (bậc sớm nhất khi bằng nhau).
    assert (request.workspace / "sparse/0/points3D.bin").read_bytes() == b"model sparse"

    strict = LadderProcess({"sparse": (0, 1), "sparse_r1": (0, 1), "sparse_r2": (0, 1)})
    gate = config(min_registered_ratio=0.75, accept_registered_ratio_after_retry=0.6)
    service, request, _ = ladder_adapter(tmp_path / "rejected", strict, gate)
    with pytest.raises(ColmapError) as error:
        service.execute(request)
    assert error.value.code == "COLMAP_REGISTRATION_LOW"
    assert len(error.value.details["retry_ladder"]) == 2

    with pytest.raises(ValidationError):
        config(min_registered_ratio=0.3, accept_registered_ratio_after_retry=0.35)


def test_cache_stores_the_successful_step_and_reuse_skips_the_ladder(tmp_path: Path) -> None:
    resume = ResumeCache(tmp_path / "resume")
    cold = LadderProcess({"sparse": None, "sparse_r1": (0, 1, 2)})
    service, request, resolver = ladder_adapter(tmp_path / "cold", cold, resume=resume)
    cold_artifact = resolver.load(service.execute(request).reference)
    warm = LadderProcess({"sparse": (0, 1, 2)})
    service, request, resolver = ladder_adapter(tmp_path / "warm", warm, resume=resume)
    warm_result = service.execute(request)
    assert not any(command[0] in {"mapper", "sequential_matcher"} for command in warm.commands)
    assert (request.workspace / "sparse/0/points3D.bin").read_bytes() == b"model sparse_r1"
    warm_artifact = resolver.load(warm_result.reference)
    assert warm_artifact.poses == cold_artifact.poses
    assert warm_artifact.retry_ladder == []


def test_old_pose_payloads_without_ladder_keep_their_bytes() -> None:
    assert "accept_registered_ratio_after_retry" not in config().model_dump(mode="json")
    assert "accept_registered_ratio_after_retry" in config(accept_registered_ratio_after_retry=0.35).model_dump()
    assert config().checksum() != config(accept_registered_ratio_after_retry=0.35).checksum()
