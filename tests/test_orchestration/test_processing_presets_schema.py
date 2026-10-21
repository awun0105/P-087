"""Per-job configuration survives artifact loading without weakening checksum checks."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.services.orchestration.artifacts import (
    ArtifactChecksumError,
    ArtifactResolver,
    FilesystemArtifactStore,
    sha256_bytes,
)
from src.services.orchestration.jobs.dispatch import resolve_job_processing
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.processing.config import (
    build_job_config,
    config_bytes,
    job_config_reference,
    load_job_config,
    load_presets,
)
from src.services.reconstruction.rgb.pose.camera_pose import ColmapConfig

PRESETS = Path(__file__).resolve().parents[2] / "configs/product/processing_presets_v1.json"


def test_sealed_job_controls_are_verified_before_downstream_consumption(tmp_path: Path) -> None:
    presets, checksum = load_presets(PRESETS)
    config = build_job_config(presets, checksum, presets.presets["minimum_quality"], None)
    payload = config_bytes(config)
    reference = job_config_reference("job-controls", sha256_bytes(payload))
    resolver = ArtifactResolver(tmp_path)
    FilesystemArtifactStore(resolver).publish(reference, payload)
    assert load_job_config("job-controls", reference.artifact_checksum, resolver) == config
    path = resolver.require(reference)
    path.write_bytes(payload + b" ")
    with pytest.raises(ArtifactChecksumError):
        load_job_config("job-controls", reference.artifact_checksum, resolver)


def test_legacy_job_without_processing_artifact_keeps_deployment_defaults(tmp_path: Path) -> None:
    assert load_job_config("job-legacy", "sha256:" + "a" * 64, ArtifactResolver(tmp_path)) is None


@pytest.mark.parametrize(
    "name",
    [
        "minimum_quality",
        "maximum",
        "video_indoor_walkthrough",
        "video_indoor_orbital_360",
        "video_single_object",
        "video_outdoor_forward",
        "photo_collection_indoor",
        "photo_collection_outdoor",
    ],
)
def test_every_preset_reaches_dispatch_with_all_six_groups(tmp_path: Path, name: str) -> None:
    presets, checksum = load_presets(PRESETS)
    config = build_job_config(presets, checksum, presets.presets[name], None)
    payload = config_bytes(config)
    reference = job_config_reference("job-controls", sha256_bytes(payload))
    resolver = ArtifactResolver(tmp_path)
    FilesystemArtifactStore(resolver).publish(reference, payload)
    job = SimpleNamespace(job_id="job-controls", config_checksum=reference.artifact_checksum)
    profile = ExecutionProfile(config_checksum=checksum, runtime_manifest_checksum="sha256:" + "d" * 64, seed=None)
    resolved = resolve_job_processing(job, profile, PRESETS, resolver, 240)
    ColmapConfig.model_validate(resolved.colmap)
    assert resolved.colmap == config.colmap and resolved.brush == config.brush
    assert resolved.sample_fps == config.sampling["sample_fps"]
    assert resolved.max_frames == config.sampling["max_frames"]
    for group in ("geometry", "scene", "simulation"):
        expected = {key.split(".", 1)[1]: value for key, value in config.params.items() if key.startswith(group + ".")}
        assert expected and getattr(resolved, group) == expected


def test_pre_extension_job_dispatch_preserves_empty_new_groups(tmp_path: Path) -> None:
    presets, checksum = load_presets(PRESETS)
    config = build_job_config(presets, checksum, presets.presets["minimum_quality"], None)
    from src.services.orchestration.processing.resources import SFM_KEYS, SPLAT_KEYS

    old_params = {key: value for key, value in config.params.items() if key in SFM_KEYS + SPLAT_KEYS}
    old = config.model_copy(
        update={
            "params": old_params,
            "geometry": {},
            "scene": {},
            "simulation": {},
            "colmap": {
                key: value
                for key, value in config.colmap.items()
                if key != "matching_mode" and not key.startswith("loop_detection_")
            },
        }
    )
    payload = config_bytes(old)
    reference = job_config_reference("job-old", sha256_bytes(payload))
    resolver = ArtifactResolver(tmp_path)
    FilesystemArtifactStore(resolver).publish(reference, payload)
    profile = ExecutionProfile(config_checksum=checksum, runtime_manifest_checksum="sha256:" + "d" * 64, seed=None)
    resolved = resolve_job_processing(
        SimpleNamespace(job_id="job-old", config_checksum=reference.artifact_checksum), profile, PRESETS, resolver, 240
    )
    assert resolved.geometry == resolved.scene == resolved.simulation == {}
    assert resolved.colmap == old.colmap
    assert resolver.require(reference).read_bytes() == payload


def test_legacy_profile_file_dispatch_keeps_independent_empty_groups(tmp_path: Path) -> None:
    """Operator profiles with only COLMAP/Brush remain executable after the schema expansion."""
    presets, checksum = load_presets(PRESETS)
    config = build_job_config(presets, checksum, presets.presets["minimum_quality"], None)
    payload = json.dumps({"colmap": config.colmap, "brush": config.brush}).encode()
    path = tmp_path / "legacy.json"
    path.write_bytes(payload)
    profile = ExecutionProfile(
        config_checksum=sha256_bytes(payload), runtime_manifest_checksum="sha256:" + "d" * 64, seed=None
    )
    job = SimpleNamespace(job_id="job-legacy", config_checksum=profile.config_checksum)
    first = resolve_job_processing(job, profile, path, ArtifactResolver(tmp_path), 240)
    second = resolve_job_processing(job, profile, path, ArtifactResolver(tmp_path), 240)
    assert first.sample_fps == 3 and first.max_frames == 240
    assert first.colmap == config.colmap and first.brush == config.brush
    assert first.geometry == first.scene == first.simulation == {}
    first.geometry["resolution_m"] = 0.1
    assert second.geometry == {}


def test_sealed_scene_and_simulation_controls_reach_consumers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services.orchestration.review.simulation_package import _job_simulation_config
    from src.services.orchestration.scene import objectify as module

    presets, checksum = load_presets(PRESETS)
    params = presets.presets["video_single_object"] | {
        "simulation.ground_plane": "disabled",
        "scene.coacd_threshold": 0.2,
        "scene.inpaint_max_new_gaussians": 10000,
    }
    config = build_job_config(presets, checksum, params, None)
    payload = config_bytes(config)
    reference = job_config_reference("job-controls", sha256_bytes(payload))
    resolver = ArtifactResolver(tmp_path)
    FilesystemArtifactStore(resolver).publish(reference, payload)
    job = SimpleNamespace(job_id="job-controls", config_checksum=reference.artifact_checksum)
    registry = SimpleNamespace(runtime_resolver=resolver, get_job=lambda _: job)
    controls = _job_simulation_config(registry, job.job_id)
    assert controls["ground_plane"] is False and controls["static_friction"] == 0.5
    seen = []

    def objectify(*args: object, **kwargs: object) -> object:
        seen.append(kwargs["scene_config"])
        if len(seen) == 1:
            raise module.ObjectifyError("fixture transient error")
        return "result"

    monkeypatch.setattr(module, "objectify", objectify)
    assert (
        module.objectify_with_retry(registry, job, None, SimpleNamespace(product_objectify_attempts=2), tmp_path, None)
        == "result"
    )
    assert len(seen) == 2 and seen[0] == seen[1]
    assert seen[0]["scene"]["max_objects"] == 1
    assert seen[0]["coacd"]["threshold"] == 0.2
    assert seen[0]["inpaint"]["max_new_gaussians"] == 10000


#: Bảng A5 của T-071 (chỉ các khóa đổi): điểm xuất phát, chỉnh lại sau lần đo trên A5000.
A5_TABLE = {
    "minimum_quality": (3, 300, 1280, 8192, 10, "sequential", 30000, 1280, 1_000_000),
    "maximum": (6, 1500, 1920, 16384, 30, "sequential", 50000, 1920, 4_000_000),
    "video_indoor_walkthrough": (3, 800, 1920, 12288, 15, "sequential_vocab_tree", 30000, 1920, 2_000_000),
    "video_indoor_orbital_360": (3, 600, 1920, 8192, 20, "sequential_vocab_tree", 30000, 1920, 2_000_000),
    "video_single_object": (3, 300, 1920, 8192, 20, "sequential", 30000, 1920, 1_500_000),
    "video_outdoor_forward": (4, 800, 1920, 16384, 12, "sequential", 30000, 1920, 3_000_000),
    "photo_collection_indoor": (3, 600, 1920, 12288, 10, "exhaustive", 30000, 1920, 2_000_000),
    "photo_collection_outdoor": (3, 800, 1920, 16384, 10, "exhaustive", 30000, 1920, 3_000_000),
}
A5_KEYS = (
    "sampling.sample_fps",
    "sampling.max_frames",
    "colmap.max_image_size",
    "colmap.max_num_features",
    "colmap.sequential_overlap",
    "colmap.matching_mode",
    "brush.total_train_iters",
    "brush.max_resolution",
    "brush.max_splats",
)


def test_a5_table_is_the_catalog_and_every_preset_sits_inside_the_new_bounds() -> None:
    presets, _ = load_presets(PRESETS)
    assert set(presets.presets) == set(A5_TABLE)
    for name, row in A5_TABLE.items():
        assert tuple(presets.presets[name][key] for key in A5_KEYS) == row, name
    bounds = {spec.key: (spec.min, spec.max) for spec in presets.parameters}
    assert bounds["sampling.max_frames"][1] == 2000
    assert bounds["colmap.sequential_overlap"][1] == 30
    assert bounds["brush.max_resolution"][1] == bounds["colmap.max_image_size"][1] == 1920
    assert bounds["brush.max_splats"][1] == 4_000_000
    for name, values in presets.presets.items():
        assert presets.validate_params(values) == values, name
        for spec in presets.parameters:
            if spec.kind != "choice":
                assert spec.min <= values[spec.key] <= spec.max, (name, spec.key)
    assert presets.fixed.colmap["min_registered_ratio"] == 0.5
    assert presets.fixed.colmap["accept_registered_ratio_after_retry"] == 0.35
    assert "T-071" in presets.resource_model.note


def test_retry_acceptance_reaches_the_colmap_config_and_is_validated() -> None:
    presets, checksum = load_presets(PRESETS)
    config = build_job_config(presets, checksum, presets.presets["video_indoor_walkthrough"], None)
    assert ColmapConfig.model_validate(config.colmap).accept_registered_ratio_after_retry == 0.35
    document = json.loads(PRESETS.read_text(encoding="utf-8"))
    for bad in (0, 0.6, "0.35", True):
        broken = json.loads(json.dumps(document))
        broken["fixed"]["colmap"]["accept_registered_ratio_after_retry"] = bad
        with pytest.raises(ValueError):
            type(presets).model_validate(broken)
