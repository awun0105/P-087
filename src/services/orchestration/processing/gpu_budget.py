"""Trần giờ GPU mỗi scene (T-043 bước 5). Thuần: giờ đã dùng tính từ cùng quy tắc `billed_usages` của bảng giá trị."""

from collections.abc import Iterable

from src.services.orchestration.processing.observed import billed_usages
from src.services.orchestration.processing.telemetry import ResourceUsage

#: Công cụ của pipeline dùng GPU (chạy qua `_run_tool`). Tách vật (`scene.*`) chưa nằm trong trần này.
GPU_TOOLS = frozenset({"preview", "finalize"})
GPU_BUDGET_CODE = "GPU_BUDGET_EXCEEDED"


class GpuBudgetExceededError(RuntimeError):
    """Scene đã dùng hoặc sắp dùng quá trần giờ GPU đã đặt; lỗi này không tự thử lại."""

    code = GPU_BUDGET_CODE


def spent_gpu_hours(usages: Iterable[ResourceUsage], job_id: str) -> float:
    """Giờ máy GPU đã tính cho job: tổng thời lượng các lượt `billed_usages` của job, đổi sang giờ."""
    return sum(usage.duration_seconds for usage in billed_usages(usages) if usage.job_id == job_id) / 3600


def start_message(spent: float, planned: float, cap: float, tool: str) -> str:
    return (
        f"Scene này đã dùng {spent:.2f} giờ GPU, vượt mức tối đa {cap:g} giờ đã đặt. "
        f"Lượt {tool} cần thêm khoảng {planned:.2f} giờ nữa, nên chưa chạy. "
        "Nâng PRODUCT_JOB_GPU_HOURS_MAX nếu scene này cần thêm giờ GPU."
    )


def running_message(spent: float, cap: float, tool: str) -> str:
    return (
        f"Scene này đã dùng {spent:.2f} giờ GPU, vượt mức tối đa {cap:g} giờ đã đặt "
        f"trong khi lượt {tool} đang chạy; đã dừng. Nâng PRODUCT_JOB_GPU_HOURS_MAX nếu cần."
    )
