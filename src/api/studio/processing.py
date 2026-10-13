"""Bảng thông số xử lý: option/preset theo file cấu hình chung và ước lượng tài nguyên."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from src.api.studio import deps
from src.services.orchestration.processing import (
    Evaluation,
    MachineCapability,
    ParameterSpec,
    evaluate,
    maximum_for_machine,
    preset_values,
)
from src.services.orchestration.processing.models import ParamValue, ScenarioPreferences
from src.services.orchestration.processing.recommender import RecommendationUnavailableError, recommend_preset

router = APIRouter()


class ProcessingOptions(BaseModel):
    """Mọi thứ UI cần để vẽ bảng thông số: spec, preset, máy worker và ước lượng mặc định."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str
    parameters: list[ParameterSpec]
    presets: dict[str, dict[str, int | float | str]]
    capability: MachineCapability | None
    default_evaluation: Evaluation
    resource_note: str
    #: Deployment có bộ che khuôn mặt/biển số (AUD-18): UI mới hiện lựa chọn tự động che.
    anonymize_available: bool = False
    #: Deployment bắt buộc che cho mọi job; UI hiện lựa chọn ở trạng thái đã bật và không cho tắt.
    anonymize_enforced: bool = False


class EvaluateRequest(BaseModel):
    """Bộ thông số cần kiểm (đủ mọi key của file cấu hình chung)."""

    model_config = ConfigDict(extra="forbid")

    params: dict[str, int | float | str]


class ProcessingSuggestion(BaseModel):
    """Scenario recommendation and its worker resource assessment."""

    model_config = ConfigDict(extra="forbid")

    preset_name: str
    params: dict[str, ParamValue]
    evaluation: Evaluation


@router.get("/processing/options", response_model=ProcessingOptions)
def get_processing_options() -> ProcessingOptions:
    """Full scenario catalog plus the current worker's resource-limited preset."""
    presets, _ = deps.presets()
    capability = deps.capability()
    settings = deps.settings()
    minimum = preset_values(presets, "minimum_quality")
    registry = deps.registry()
    observed = deps.observed_resource_budget(
        registry,
        minimum,
        capability.gpu_name if capability is not None else None,
        colmap_use_gpu=getattr(settings, "product_colmap_use_gpu", False),
    )
    return ProcessingOptions(
        profile_id=presets.profile_id,
        parameters=presets.parameters,
        presets={
            **{name: preset_values(presets, name) for name in presets.presets},
            "machine_maximum": maximum_for_machine(presets, capability),
        },
        capability=capability,
        default_evaluation=evaluate(presets, minimum, capability, observed=observed),
        resource_note=presets.resource_model.note,
        anonymize_available=deps.anonymizer_available(),
        anonymize_enforced=deps.anonymize_enforced(),
    )


@router.post("/processing/evaluate", response_model=Evaluation)
def evaluate_processing(request: EvaluateRequest) -> Evaluation:
    """Ước lượng tài nguyên của bộ thông số so với máy worker (đỏ = có thể crash)."""
    presets, _ = deps.presets()
    capability = deps.capability()
    settings = deps.settings()
    registry = deps.registry()
    observed = deps.observed_resource_budget(
        registry,
        request.params,
        capability.gpu_name if capability is not None else None,
        colmap_use_gpu=getattr(settings, "product_colmap_use_gpu", False),
    )
    try:
        return evaluate(presets, request.params, capability, observed=observed)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.post("/processing/suggest", response_model=ProcessingSuggestion)
def suggest_processing(request: ScenarioPreferences) -> ProcessingSuggestion:
    """Recommend valid scenario controls against the same worker used by evaluation."""
    presets, _ = deps.presets()
    capability = deps.capability()
    try:
        name, params = recommend_preset(request, capability, presets)
    except RecommendationUnavailableError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    settings = deps.settings()
    observed = deps.observed_resource_budget(
        deps.registry(),
        params,
        capability.gpu_name if capability is not None else None,
        colmap_use_gpu=getattr(settings, "product_colmap_use_gpu", False),
    )
    return ProcessingSuggestion(
        preset_name=name, params=params, evaluation=evaluate(presets, params, capability, observed=observed)
    )
