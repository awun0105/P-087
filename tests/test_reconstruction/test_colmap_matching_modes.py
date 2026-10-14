import hashlib
import struct
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.identity import canonical_json_bytes
from src.services.reconstruction.adapters.colmap import ColmapRequest
from src.services.reconstruction.adapters.colmap_runtime import (
    ColmapError,
    ColmapProcess,
    ColmapRuntimeSettings,
    reconstruction_commands,
)
from tests.test_reconstruction.test_rec03_colmap import adapter, config


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
