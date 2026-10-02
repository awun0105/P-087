"""Ngân sách tài nguyên của một job suy từ số đo các lượt chạy trước trên cùng loại máy.

Không có hệ số viết tay: một lượt chạy có mọi thông số số học lớn hơn hoặc bằng job
đang xét ("trội hơn") cho một chặn trên của mức job đó sẽ dùng. Cùng một cấu hình, video
khác nhau cho mức dùng khác nhau, nên với mỗi cấu hình lấy mức cao nhất đã thấy; giữa các
cấu hình trội hơn lấy cấu hình cho chặn chặt nhất. Chưa có lượt nào trội hơn thì trả None:
nơi gọi phải coi là "chưa biết", không được đoán.

Đây vẫn là suy luận từ mẫu đã đo, không phải bảo đảm: video dài hơn mọi video từng chạy
có thể dùng nhiều hơn. Worker còn kiểm phần đang trống thật lúc nhận job và có đường chạy
lại khi hết bộ nhớ.
"""

import logging
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import ValidationError

from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing.models import ParamValue
from src.services.orchestration.processing.telemetry import ResourceUsage

logger = logging.getLogger(__name__)
Measured = Literal["vram", "ram"]


def numeric_params(params: dict[str, ParamValue]) -> dict[str, float]:
    """Thông số số học của cấu hình job (thông số dạng lựa chọn không có thứ tự lớn/nhỏ)."""
    return {key: float(value) for key, value in params.items() if isinstance(value, int | float) and value is not True}


def dominates(run: dict[str, float], job: dict[str, float]) -> bool:
    """Lượt chạy `run` nặng ít nhất bằng `job` ở mọi thông số (cùng bộ thông số)."""
    return set(run) == set(job) and all(run[key] >= job[key] for key in job)


def _vram(usage: ResourceUsage) -> float | None:
    """VRAM lượt chạy đã dùng: theo PID nếu driver báo; nếu không, mức tăng của cả GPU khi nó chạy một mình."""
    if usage.peak_vram_gb is not None:
        return usage.peak_vram_gb
    if usage.shared_gpu is False and usage.peak_gpu_used_gb is not None and usage.gpu_used_before_gb is not None:
        return max(0.0, usage.peak_gpu_used_gb - usage.gpu_used_before_gb)
    return None


def load_usages(database: RuntimeDatabase) -> list[ResourceUsage]:
    """Mọi bản ghi đo đọc được; dòng hỏng hoặc của schema lạ bị bỏ qua, không làm hỏng gate."""
    with database.transaction() as tx:
        rows = tx.execute("SELECT payload FROM r2s_resource_usage").fetchall()
    usages: list[ResourceUsage] = []
    for row in rows:
        try:
            usages.append(ResourceUsage.model_validate_json(row[0]))
        except ValidationError:
            logger.warning("Bỏ qua một bản ghi resource usage không đọc được")
    return usages


def observed_budget(
    usages: Iterable[ResourceUsage],
    *,
    tools: Sequence[str],
    params: dict[str, float],
    gpu_name: str | None,
    runtime_manifest_checksum: str,
) -> dict[Measured, float] | None:
    """Chặn trên VRAM/RAM (GiB) cho job chạy các `tools`; None nếu thiếu số đo cho bất kỳ tool nào.

    Chỉ dùng lượt hoàn tất trên cùng model GPU và cùng runtime (đổi Brush/SAM2 là số đo cũ
    không còn đúng).
    """
    relevant = [
        usage
        for usage in usages
        if usage.outcome == "completed"
        and usage.params is not None
        and usage.gpu_name == gpu_name
        and usage.runtime_manifest_checksum == runtime_manifest_checksum
        and dominates(usage.params, params)
    ]
    budget: dict[Measured, float] = {"vram": 0.0, "ram": 0.0}
    for tool in tools:
        groups: dict[tuple[tuple[str, float], ...], dict[Measured, float]] = {}
        for usage in relevant:
            vram = _vram(usage)
            if usage.tool != tool or vram is None or usage.peak_ram_gb is None:
                continue
            group = groups.setdefault(tuple(sorted(usage.params.items())), {"vram": 0.0, "ram": 0.0})  # type: ignore[union-attr]
            group["vram"], group["ram"] = max(group["vram"], vram), max(group["ram"], usage.peak_ram_gb)
        if not groups:
            return None
        for name in ("vram", "ram"):
            budget[name] = max(budget[name], min(group[name] for group in groups.values()))
    return budget


def exhausted_before(usages: Iterable[ResourceUsage], job_id: str) -> bool:
    """Job này đã từng có lượt chạy chết vì hết bộ nhớ chưa (để chỉ tự chạy lại một lần, một mình)."""
    return any(usage.job_id == job_id and usage.exhausted for usage in usages)
