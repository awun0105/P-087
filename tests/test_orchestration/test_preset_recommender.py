"""Scenario coverage, deterministic resource scaling and impossible-budget rejection."""

from datetime import UTC, datetime
from itertools import product
from pathlib import Path

import pytest

from src.services.orchestration.processing.config import load_presets
from src.services.orchestration.processing.models import MachineCapability, ScenarioPreferences
from src.services.orchestration.processing.recommender import RecommendationUnavailableError, recommend_preset
from src.services.orchestration.processing.resources import SFM_KEYS, SPLAT_KEYS, estimate_gb


def machine(vram: float, ram: float = 32, disk: float = 100) -> MachineCapability:
    return MachineCapability(
        worker_id="fixture",
        measured_at=datetime.now(UTC),
        gpu_name="fixture GPU",
        vram_total_gb=vram,
        cpu_count=8,
        ram_total_gb=ram,
        disk_free_gb=disk,
    )


def preferences(**changes: str) -> ScenarioPreferences:
    return ScenarioPreferences.model_validate(
        dict(input_type="video_continuous", environment="indoor", subject_scope="full_room", target_capacity="balanced")
        | changes
    )


@pytest.mark.parametrize(
    "input_type,environment,scope,target",
    list(
        product(
            ["video_continuous", "video_loop_360", "photo_set"],
            ["indoor", "outdoor"],
            ["single_object", "full_room"],
            ["minimum_quality", "balanced", "machine_maximum"],
        )
    ),
)
def test_every_scenario_has_a_valid_deterministic_catalog_entry(
    input_type: str, environment: str, scope: str, target: str
) -> None:
    presets, _ = load_presets(Path("configs/product/processing_presets_v1.json"))
    prefs = preferences(input_type=input_type, environment=environment, subject_scope=scope, target_capacity=target)
    worker = machine(24)
    original = presets.model_dump()
    name, params = recommend_preset(prefs, worker, presets)
    expected = (
        f"photo_collection_{environment}"
        if input_type == "photo_set"
        else "video_single_object"
        if scope == "single_object"
        else "video_outdoor_forward"
        if environment == "outdoor"
        else "video_indoor_orbital_360"
        if input_type == "video_loop_360"
        else "video_indoor_walkthrough"
    )
    assert name == expected
    assert presets.validate_params(params) == params
    assert (
        params["colmap.matching_mode"]
        == {"photo_set": "exhaustive", "video_loop_360": "sequential_vocab_tree", "video_continuous": "sequential"}[
            input_type
        ]
    )
    assert params["geometry.external_fill_size_m"] == (1.6 if environment == "indoor" and scope == "full_room" else 0)
    assert params["geometry.floor_fill_size_m"] == (1.6 if environment == "outdoor" and scope == "full_room" else 0)
    assert params["simulation.ground_plane"] == ("enabled" if environment == "indoor" else "disabled")
    if scope == "single_object":
        assert params["scene.max_objects"] == 1
    assert recommend_preset(prefs, worker, presets) == (name, params)
    params["brush.max_splats"] = 0
    assert presets.model_dump() == original


def test_four_and_twenty_four_gb_workers_scale_training_separately_from_ram() -> None:
    presets, _ = load_presets(Path("configs/product/processing_presets_v1.json"))
    prefs = preferences(target_capacity="machine_maximum")
    _, small = recommend_preset(prefs, machine(4), presets)
    _, large = recommend_preset(prefs, machine(24), presets)
    for key in ("brush.max_splats", "brush.max_resolution", "brush.total_train_iters"):
        assert small[key] < large[key]
    for params, vram in ((small, 4), (large, 24)):
        required = estimate_gb(presets.resource_model, params)
        assert required["vram"] < vram * presets.resource_model.warn_ratio
        assert required["ram"] < 32 * presets.resource_model.warn_ratio
        assert required["disk"] < 100 * presets.resource_model.warn_ratio
    assert small["sampling.max_frames"] == large["sampling.max_frames"]


@pytest.mark.parametrize("target", ["minimum_quality", "balanced", "machine_maximum"])
def test_unusable_worker_is_not_recommended_as_safe(target: str) -> None:
    presets, _ = load_presets(Path("configs/product/processing_presets_v1.json"))
    for worker in (machine(0), machine(1), machine(4, ram=0.5), machine(4, disk=0.01)):
        with pytest.raises(RecommendationUnavailableError):
            recommend_preset(preferences(target_capacity=target), worker, presets)


def test_unknown_worker_uses_minimum_without_claiming_measurement() -> None:
    presets, _ = load_presets(Path("configs/product/processing_presets_v1.json"))
    _, values = recommend_preset(preferences(target_capacity="machine_maximum"), None, presets)
    assert all(values[key] == presets.presets["minimum_quality"][key] for key in SFM_KEYS + SPLAT_KEYS)
    assert values["geometry.external_fill_size_m"] == 1.6


def test_busy_worker_uses_recorded_idle_budget() -> None:
    presets, _ = load_presets(Path("configs/product/processing_presets_v1.json"))
    idle = machine(24).model_copy(
        update={
            "idle_measured_at": datetime.now(UTC),
            "idle_vram_free_gb": 20,
            "idle_ram_available_gb": 24,
            "idle_disk_free_gb": 80,
        }
    )
    busy = idle.model_copy(
        update={"headroom_measured": True, "vram_free_gb": 0.1, "ram_available_gb": 0.2, "disk_free_gb": 1}
    )
    prefs = preferences(target_capacity="machine_maximum")
    assert recommend_preset(prefs, busy, presets) == recommend_preset(prefs, idle, presets)


def test_incomplete_idle_measurement_fails_instead_of_guessing() -> None:
    presets, _ = load_presets(Path("configs/product/processing_presets_v1.json"))
    worker = machine(24).model_copy(update={"idle_measured_at": datetime.now(UTC)})
    with pytest.raises(RecommendationUnavailableError):
        recommend_preset(preferences(), worker, presets)


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_type", "other"),
        ("environment", "space"),
        ("subject_scope", "none"),
        ("target_capacity", "unbounded"),
        ("unknown", "value"),
    ],
)
def test_scenario_schema_rejects_unknown_choices(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        preferences(**{field: value})
