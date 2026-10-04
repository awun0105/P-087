"""Ước lượng tài nguyên của một bộ thông số so với máy worker, và preset "tối đa cho máy này".

Đây là heuristic để cảnh báo trước khi chạy (hệ số nằm trong file cấu hình chung),
không phải phép đo. Mục tiêu là chặn cấu hình gần như chắc chắn crash (hết VRAM,
RAM, đĩa) và báo vàng khi sát ngưỡng.
"""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.services.orchestration.processing.models import (
    MachineCapability,
    ParamValue,
    ProcessingPresets,
    ResourceModel,
)

Status = Literal["ok", "warn", "danger", "unknown"]
Resource = Literal["vram", "ram", "disk"]

#: Thông số ảnh hưởng mạnh nhất tới từng tài nguyên (để tô đỏ đúng ô trên UI).
DRIVERS: dict[Resource, tuple[str, ...]] = {
    "vram": ("brush.max_splats", "brush.max_resolution"),
    "ram": ("sampling.max_frames", "colmap.max_num_features", "colmap.max_image_size"),
    "disk": ("sampling.max_frames", "brush.max_splats"),
}


class ResourceEstimate(BaseModel):
    """Một tài nguyên: cần bao nhiêu (ước lượng) so với máy có bao nhiêu."""

    model_config = ConfigDict(extra="forbid")

    resource: Resource
    required_gb: float
    available_gb: float | None
    status: Status
    message: str


class ParameterStatus(BaseModel):
    """Trạng thái tô màu cho một ô thông số trên UI."""

    model_config = ConfigDict(extra="forbid")

    key: str
    status: Status
    message: str | None = None


class Evaluation(BaseModel):
    """Kết quả kiểm tra; `blocking` khi vượt năng lực máy, không chỉ bận tạm thời."""

    model_config = ConfigDict(extra="forbid")

    resources: list[ResourceEstimate]
    parameters: list[ParameterStatus]
    blocking: bool
    note: str


def _num(params: dict[str, ParamValue], key: str) -> float:
    return float(params[key])


def estimate_gb(model: ResourceModel, params: dict[str, ParamValue]) -> dict[Resource, float]:
    """VRAM (Brush), RAM (COLMAP + giải mã ảnh), đĩa (frame + workspace + output)."""
    frames = _num(params, "sampling.max_frames")
    splats_m = _num(params, "brush.max_splats") / 1e6
    train_mp = _num(params, "brush.max_resolution") ** 2 * 9 / 16 / 1e6
    decode_mp = _num(params, "colmap.max_image_size") ** 2 * 9 / 16 / 1e6
    features = _num(params, "colmap.max_num_features")
    vram = (
        model.vram_base_gb + splats_m * model.vram_per_million_splats_gb + train_mp * model.vram_per_train_megapixel_gb
    )
    ram = (
        model.ram_base_gb
        + frames * features * model.ram_feature_bytes / 1e9
        + frames * decode_mp * model.ram_per_decode_megapixel_gb
    )
    disk = (
        frames * model.assumed_video_megapixels * model.disk_per_frame_megapixel_gb * model.disk_workspace_factor
        + splats_m * model.disk_per_million_splats_gb
    )
    return {"vram": round(vram, 2), "ram": round(ram, 2), "disk": round(disk, 2)}


def _available(capability: MachineCapability | None) -> dict[Resource, float | None]:
    if capability is None:
        return {"vram": None, "ram": None, "disk": None}
    if capability.headroom_measured:
        return {"vram": capability.vram_free_gb, "ram": capability.ram_available_gb, "disk": capability.disk_free_gb}
    return {"vram": capability.vram_total_gb, "ram": capability.ram_total_gb, "disk": capability.disk_free_gb}


def _idle(capability: MachineCapability | None) -> dict[Resource, float | None] | None:
    """Phần trống lúc pipeline không dùng máy; None khi worker chưa từng đo lúc rảnh."""
    if capability is None or capability.idle_measured_at is None:
        return None
    return {
        "vram": capability.idle_vram_free_gb,
        "ram": capability.idle_ram_available_gb,
        "disk": capability.idle_disk_free_gb,
    }


def _status(model: ResourceModel, required: float, available: float | None) -> Status:
    if available is None:
        return "unknown"
    if available <= 0:
        return "danger"
    ratio = required / available
    if ratio >= model.danger_ratio:
        return "danger"
    if ratio >= model.warn_ratio:
        return "warn"
    return "ok"


_LABEL: dict[Resource, str] = {"vram": "VRAM GPU", "ram": "RAM", "disk": "Ổ đĩa trống"}


def evaluate(
    presets: ProcessingPresets, params: dict[str, ParamValue], capability: MachineCapability | None
) -> Evaluation:
    """So ước lượng với máy worker; ô thông số gây đỏ/vàng được đánh dấu tương ứng."""
    model = presets.resource_model
    values = presets.validate_params(params)
    required = estimate_gb(model, values)
    available = _available(capability)
    capacity: dict[Resource, float | None] = {
        "vram": capability.vram_total_gb if capability else None,
        "ram": capability.ram_total_gb if capability else None,
        # Worker cũ không báo tổng dung lượng ổ: chỉ khi đó mới coi phần trống là giới hạn cứng.
        "disk": (
            capability.disk_total_gb
            if capability and capability.disk_total_gb is not None
            else (capability.disk_free_gb if capability and not capability.headroom_measured else None)
        ),
    }
    idle = _idle(capability)
    resources: list[ResourceEstimate] = []
    marks: dict[str, ParameterStatus] = {}
    rank = {"ok": 0, "unknown": 0, "warn": 1, "danger": 2}
    for resource in ("vram", "ram", "disk"):
        status = _status(model, required[resource], available[resource])
        have = available[resource]
        if status == "unknown":
            message = f"Chưa đo được {_LABEL[resource]} của máy xử lý"
        else:
            message = f"Cần khoảng {required[resource]:.1f} GB / máy có {have:.1f} GB {_LABEL[resource]}"
            if status == "danger":
                if (
                    capability
                    and capability.headroom_measured
                    and _status(model, required[resource], capacity[resource]) != "danger"
                ):
                    # Lúc máy rảnh cũng không đủ thì chờ job khác xong không giải quyết được.
                    if idle is not None and _status(model, required[resource], idle[resource]) == "danger":
                        message += (
                            " — lúc máy xử lý rảnh cũng không đủ; job sẽ chờ tới khi phần đang bị chiếm"
                            " được giải phóng, hoặc giảm thông số được tô đỏ"
                        )
                    else:
                        message += " — hiện thiếu tài nguyên; job sẽ chờ và tự chạy tiếp khi đủ"
                else:
                    message += " — có thể crash, hãy giảm thông số được tô đỏ"
        resources.append(
            ResourceEstimate(
                resource=resource,
                required_gb=required[resource],
                available_gb=have,
                status=status,
                message=message,
            )
        )
        if status in {"warn", "danger"}:
            for key in DRIVERS[resource]:
                current = marks.get(key)
                if current is None or rank[status] > rank[current.status]:
                    marks[key] = ParameterStatus(key=key, status=status, message=message)
    if values["brush.max_splats"] >= model.viewer_heavy_splats and "brush.max_splats" not in marks:
        marks["brush.max_splats"] = ParameterStatus(
            key="brush.max_splats",
            status="warn",
            message="Scene rất nặng: máy người xem có GPU yếu có thể giật khi mở",
        )
    parameters = [marks.get(spec.key, ParameterStatus(key=spec.key, status="ok")) for spec in presets.parameters]
    return Evaluation(
        resources=resources,
        parameters=parameters,
        # Bận tạm thời không cấm enqueue. Chỉ chặn cấu hình vượt capacity thật đã biết.
        blocking=any(_status(model, required[name], capacity[name]) == "danger" for name in ("vram", "ram", "disk")),
        note=model.note,
    )


def _snap(value: float, minimum: float, step: float) -> float:
    return minimum + math.floor((value - minimum) / step + 1e-9) * step


def interpolate(
    presets: ProcessingPresets, low: dict[str, ParamValue], high: dict[str, ParamValue], t: float
) -> dict[str, ParamValue]:
    """Điểm giữa hai bộ thông số (t=0 → low, t=1 → high), làm tròn xuống theo step.

    Mọi thông số số tăng cùng nhịp nên không có chuyện một thông số bị ép cực thấp
    trong khi thông số khác vẫn cực cao. Thông số choice giữ theo `low`.
    """
    values: dict[str, ParamValue] = {}
    for spec in presets.parameters:
        a, b = low[spec.key], high[spec.key]
        if spec.kind == "choice" or isinstance(a, str) or isinstance(b, str):
            values[spec.key] = a
            continue
        raw = float(a) + (float(b) - float(a)) * t
        snapped = max(spec.min or 0.0, min(spec.max or raw, _snap(raw, spec.min or 0.0, spec.step or 1.0)))
        values[spec.key] = int(round(snapped)) if spec.kind == "integer" else round(snapped, 4)
    return values


def _fits(model: ResourceModel, values: dict[str, ParamValue], available: dict[Resource, float | None]) -> bool:
    required = estimate_gb(model, values)
    return all(have is None or required[name] < have * model.warn_ratio for name, have in available.items())


def maximum_for_machine(presets: ProcessingPresets, capability: MachineCapability | None) -> dict[str, ParamValue]:
    """Bộ thông số cao nhất giữa preset tối thiểu và tối đa mà mọi tài nguyên dưới ngưỡng vàng.

    Tính theo mốc "máy rảnh" worker ghi lại, không theo phần đang trống tức thời: lúc
    worker đang chạy job khác, phần trống đã bị chính job đó chiếm và sẽ được trả lại
    trước khi job mới chạy (job mới chờ trong hàng đợi với nguyên cấu hình). Worker chưa
    từng đo lúc rảnh thì dùng tổng năng lực máy.

    Tìm nhị phân hệ số nội suy t. Máy yếu tới mức preset tối thiểu cũng không vừa
    thì nội suy tiếp xuống phía min của từng thông số. Không có số đo máy → preset
    tối thiểu (không đoán).
    """
    minimum = dict(presets.presets["minimum_quality"])
    if capability is None:
        return minimum
    model = presets.resource_model
    idle = _idle(capability)
    available: dict[Resource, float | None] = idle or {
        "vram": capability.vram_total_gb,
        "ram": capability.ram_total_gb,
        "disk": capability.disk_free_gb,
    }
    if idle is not None and any(value is None for value in idle.values()):
        return minimum  # Không suy maximum từ mốc rảnh thiếu số đo RAM/VRAM.
    floor = {spec.key: (spec.min if spec.kind != "choice" else minimum[spec.key]) for spec in presets.parameters}
    if _fits(model, minimum, available):
        low, high = minimum, dict(presets.presets["maximum"])
    else:
        low, high = floor, minimum  # type: ignore[assignment]
    best, lo, hi = interpolate(presets, low, high, 0.0), 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        candidate = interpolate(presets, low, high, mid)
        if _fits(model, candidate, available):
            best, lo = candidate, mid
        else:
            hi = mid
    if _fits(model, interpolate(presets, low, high, 1.0), available):
        best = interpolate(presets, low, high, 1.0)
    return presets.validate_params(best)
