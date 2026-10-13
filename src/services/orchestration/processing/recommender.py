"""Deterministic scenario selection using the shared calibrated resource model."""

from typing import Literal

from src.services.orchestration.processing.models import (
    MachineCapability,
    ParamValue,
    ProcessingPresets,
    ScenarioPreferences,
)
from src.services.orchestration.processing.resources import SFM_KEYS, SPLAT_KEYS, estimate_gb, maximum_for_machine

CapacityTarget = Literal["minimum_quality", "balanced", "machine_maximum"]


class RecommendationUnavailableError(ValueError):
    """Even the declared minimum cannot fit the known worker resource budget."""


def select_preset_name(preferences: ScenarioPreferences) -> str:
    """Photo capture takes precedence; video object scans share one scenario preset."""
    if preferences.input_type == "photo_set":
        return f"photo_collection_{preferences.environment}"
    if preferences.subject_scope == "single_object":
        return "video_single_object"
    if preferences.environment == "outdoor":
        return "video_outdoor_forward"
    return "video_indoor_orbital_360" if preferences.input_type == "video_loop_360" else "video_indoor_walkthrough"


def scale_for_machine(
    params: dict[str, ParamValue],
    capability: MachineCapability | None,
    target: CapacityTarget,
    *,
    presets: ProcessingPresets,
) -> dict[str, ParamValue]:
    """Cap resource drivers at scenario, minimum-quality or machine-maximum ceilings.

    Unknown machines use minimum-quality values without claiming safety. Known
    budgets use the existing idle-baseline search and fail if its floor cannot fit.
    """
    if target not in {"minimum_quality", "balanced", "machine_maximum"}:
        raise ValueError("unknown capacity target")
    values = presets.validate_params(params)
    low, high = dict(values), dict(values)
    for spec in presets.parameters:
        if spec.key not in SFM_KEYS + SPLAT_KEYS or spec.kind == "choice":
            continue
        minimum = min(values[spec.key], presets.presets["minimum_quality"][spec.key])
        low[spec.key] = int(spec.min) if spec.kind == "integer" else spec.min
        high[spec.key] = (
            presets.presets["maximum"][spec.key]
            if target == "machine_maximum" and capability is not None
            else minimum
            if target == "minimum_quality" or capability is None
            else values[spec.key]
        )
    if capability is None:
        return presets.validate_params(high)
    if capability.vram_total_gb is None or capability.vram_total_gb <= 0:
        raise RecommendationUnavailableError("Máy xử lý chưa có GPU/VRAM phù hợp để dựng 3DGS.")
    search = presets.model_copy(update={"presets": {"minimum_quality": low, "maximum": high}})
    scaled = maximum_for_machine(search, capability)
    available = (
        (capability.idle_vram_free_gb, capability.idle_ram_available_gb, capability.idle_disk_free_gb)
        if capability.idle_measured_at is not None
        else (capability.vram_total_gb, capability.ram_total_gb, capability.disk_free_gb)
    )
    required = estimate_gb(presets.resource_model, scaled)
    if any(
        budget is None or required[resource] >= budget * presets.resource_model.warn_ratio
        for resource, budget in zip(("vram", "ram", "disk"), available, strict=True)
    ):
        raise RecommendationUnavailableError("Cấu hình thấp nhất vẫn vượt ngân sách tài nguyên đã đo của máy xử lý.")
    return presets.validate_params(scaled)


def recommend_preset(
    preferences: ScenarioPreferences, capability: MachineCapability | None, presets: ProcessingPresets
) -> tuple[str, dict[str, ParamValue]]:
    """Select a catalog entry, preserve its choices, and scale numeric resource drivers."""
    name = select_preset_name(preferences)
    if name not in presets.presets:
        raise ValueError(f"scenario preset missing from catalog: {name}")
    params = scale_for_machine(presets.presets[name], capability, preferences.target_capacity, presets=presets)
    return name, params
