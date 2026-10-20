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

Phase = Literal["preview", "finalize"]
#: Công cụ runner chạy trong mỗi lần nhận job; ngân sách đo được phải phủ hết các công cụ này.
PHASE_TOOLS: dict[Phase, tuple[str, ...]] = {"preview": ("preview",), "finalize": ("finalize", "scene_extract")}
#: Bước phụ trợ chạy cùng lần nhận job nhưng chỉ khi deployment bật (đề xuất tỉ lệ bằng MoGe-2).
PHASE_OPTIONAL_TOOLS: dict[Phase, tuple[str, ...]] = {"preview": ("metric_proposal",), "finalize": ()}


def numeric_params(params: dict[str, ParamValue]) -> dict[str, float]:
    """Thông số số học của cấu hình job (thông số dạng lựa chọn không có thứ tự lớn/nhỏ)."""
    return {key: float(value) for key, value in params.items() if isinstance(value, int | float) and value is not True}


def resource_observation_params(params: dict[str, ParamValue], *, colmap_use_gpu: bool) -> dict[str, float]:
    """Khóa observation theo cờ COLMAP GPU; cờ false giữ tương thích số đo CPU lịch sử."""
    return numeric_params(params) | ({"colmap.use_gpu": 1.0} if colmap_use_gpu else {})


def dominates(run: dict[str, float], job: dict[str, float]) -> bool:
    """Lượt chạy `run` nặng ít nhất bằng `job` ở mọi thông số (cùng bộ thông số)."""
    return set(run) == set(job) and all(run[key] >= job[key] for key in job)


def usage_vram(usage: ResourceUsage) -> float | None:
    """VRAM lượt chạy đã dùng: theo PID nếu driver báo; nếu không, mức tăng của cả GPU khi nó chạy một mình."""
    if usage.peak_vram_gb is not None:
        return usage.peak_vram_gb
    if usage.shared_gpu is False and usage.peak_gpu_used_gb is not None and usage.gpu_used_before_gb is not None:
        return max(0.0, usage.peak_gpu_used_gb - usage.gpu_used_before_gb)
    return None


def load_usages(database: RuntimeDatabase, *, job_ids: Sequence[str] | None = None) -> list[ResourceUsage]:
    """Mọi bản ghi đo đọc được (hoặc chỉ của `job_ids`, dùng index theo job); dòng hỏng hoặc schema lạ bị bỏ qua."""
    if job_ids is not None and not job_ids:
        return []
    with database.transaction() as tx:
        if job_ids is None:
            rows = tx.execute("SELECT payload FROM r2s_resource_usage").fetchall()
        else:
            marks = ",".join("?" for _ in job_ids)
            rows = tx.execute(
                f"SELECT payload FROM r2s_resource_usage WHERE job_id IN ({marks})", tuple(job_ids)
            ).fetchall()
    usages: list[ResourceUsage] = []
    for row in rows:
        try:
            usages.append(ResourceUsage.model_validate_json(row[0]))
        except ValidationError:
            logger.warning("Bỏ qua một bản ghi resource usage không đọc được")
    return usages


#: Tiền tố tool của hàng đợi tách vật (`scene.<mode>`); không thuộc lượt chạy pipeline của job.
SCENE_TOOL_PREFIX = "scene."


def is_scene_operation(usage: ResourceUsage) -> bool:
    """Bản ghi của hàng đợi tách vật (Tạo mesh, dựng lại vùng...), không phải một bước của pipeline."""
    return usage.tool.startswith(SCENE_TOOL_PREFIX)


def pipeline_usages(usages: Iterable[ResourceUsage]) -> list[ResourceUsage]:
    """Bỏ mọi bản ghi `scene.*`. Mọi chỗ đọc số đo để quyết định cho pipeline (thẻ đánh giá, xếp lại,
    ngân sách, hiệu chỉnh) phải đi qua đây, để một việc làm sau đó không đổi kết quả của lượt chạy đã xong."""
    return [usage for usage in usages if not is_scene_operation(usage)]


def billed_usages(usages: Iterable[ResourceUsage]) -> list[ResourceUsage]:
    """Các lượt được tính vào thời gian máy (và giờ GPU) của job. Hai quy tắc theo tool:

    - Tool của pipeline (không bắt đầu bằng `scene.`): mỗi (job, tool) chỉ lượt chạy xong gần nhất, nên chạy lại một bước
      pipeline không bị cộng dồn.
    - Tool `scene.*` (hàng đợi tách vật): mọi lượt chạy xong, vì mỗi lần Tạo mesh hay dựng lại vùng là một việc thật.
    Chỉ lượt `completed`. Đây là nguồn duy nhất của quy tắc: `processing_seconds` và bảng giá trị cùng đọc từ đây.
    """
    latest: dict[tuple[str, str], ResourceUsage] = {}
    billed: list[ResourceUsage] = []
    for usage in usages:
        if usage.outcome != "completed":
            continue
        if is_scene_operation(usage):
            billed.append(usage)
            continue
        key = (usage.job_id, usage.tool)
        if key not in latest or usage.completed_at > latest[key].completed_at:
            latest[key] = usage
    return billed + list(latest.values())


def processing_seconds(usages: Iterable[ResourceUsage]) -> dict[str, float]:
    """Thời gian máy đã xử lý của từng job: tổng thời lượng các lượt của `billed_usages`.

    Không gồm lúc nằm trong hàng đợi và lúc chờ người dùng thao tác (vd. xác nhận tỉ lệ mét), vì đó không phải thời
    gian hệ thống làm việc. Job chưa có bước nào được đo (dựng trước khi có số đo) không có trong kết quả.
    """
    totals: dict[str, float] = {}
    for usage in billed_usages(usages):
        totals[usage.job_id] = totals.get(usage.job_id, 0.0) + usage.duration_seconds
    return totals


def observed_budget(
    usages: Iterable[ResourceUsage],
    *,
    tools: Sequence[str],
    optional_tools: Sequence[str] = (),
    params: dict[str, float],
    gpu_name: str | None,
    runtime_manifest_checksum: str,
) -> dict[Measured, float] | None:
    """Chặn trên VRAM/RAM (GiB) cho job chạy các `tools`; None nếu thiếu số đo cho bất kỳ tool nào.

    `optional_tools` là bước phụ trợ có thể không bật trên deployment: có số đo thì tính vào, chưa có
    thì bỏ qua thay vì coi cả job là chưa biết.

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
    for tool in [*tools, *optional_tools]:
        groups: dict[tuple[tuple[str, float], ...], dict[Measured, float]] = {}
        for usage in relevant:
            vram = usage_vram(usage)
            if usage.tool != tool or vram is None or usage.peak_ram_gb is None:
                continue
            group = groups.setdefault(tuple(sorted(usage.params.items())), {"vram": 0.0, "ram": 0.0})  # type: ignore[union-attr]
            group["vram"], group["ram"] = max(group["vram"], vram), max(group["ram"], usage.peak_ram_gb)
        if not groups:
            if tool in optional_tools:
                continue  # Bước phụ trợ chưa từng chạy trên máy này (vd. không bật): không chặn ngân sách.
            return None
        for name in ("vram", "ram"):
            budget[name] = max(budget[name], min(group[name] for group in groups.values()))
    return budget


def exhausted_before(usages: Iterable[ResourceUsage], job_id: str) -> bool:
    """Job này đã từng có lượt chạy chết vì hết bộ nhớ chưa (để chỉ tự chạy lại một lần, một mình)."""
    return any(usage.job_id == job_id and usage.exhausted for usage in usages)


def observed_for_config(
    usages: Iterable[ResourceUsage],
    *,
    params: dict[str, ParamValue],
    gpu_name: str | None,
    runtime_manifest_checksum: str,
    colmap_use_gpu: bool = False,
) -> dict[Measured, float] | None:
    """Ngân sách VRAM/RAM (GiB) cao nhất giữa các phase nếu mọi phase đều đã đo; None nếu thiếu bất kỳ phase nào."""
    usage_list = list(usages)
    num_params = resource_observation_params(params, colmap_use_gpu=colmap_use_gpu)
    vram_max = 0.0
    ram_max = 0.0
    for phase in PHASE_TOOLS:
        budget = observed_budget(
            usage_list,
            tools=PHASE_TOOLS[phase],
            optional_tools=PHASE_OPTIONAL_TOOLS[phase],
            params=num_params,
            gpu_name=gpu_name,
            runtime_manifest_checksum=runtime_manifest_checksum,
        )
        if budget is None:
            return None
        vram_max = max(vram_max, budget["vram"])
        ram_max = max(ram_max, budget["ram"])
    return {"vram": round(vram_max, 2), "ram": round(ram_max, 2)}
