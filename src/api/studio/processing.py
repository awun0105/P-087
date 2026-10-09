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


class EvaluateRequest(BaseModel):
    """Bộ thông số cần kiểm (đủ mọi key của file cấu hình chung)."""

    model_config = ConfigDict(extra="forbid")

    params: dict[str, int | float | str]


@router.get("/processing/options", response_model=ProcessingOptions)
def get_processing_options() -> ProcessingOptions:
    """Thông số chỉnh được + preset tối thiểu/tối đa/tối đa cho máy worker hiện tại."""
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
            "minimum_quality": minimum,
            "maximum": preset_values(presets, "maximum"),
            "machine_maximum": maximum_for_machine(presets, capability),
        },
        capability=capability,
        default_evaluation=evaluate(presets, minimum, capability, observed=observed),
        resource_note=presets.resource_model.note,
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
