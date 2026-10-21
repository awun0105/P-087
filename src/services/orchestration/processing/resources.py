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

#: Nhóm thông số phục hồi tư thế camera và SfM (chủ yếu quyết định RAM và đĩa).
SFM_KEYS: tuple[str, ...] = (
    "sampling.sample_fps",
    "sampling.max_frames",
    "colmap.max_image_size",
    "colmap.max_num_features",
    "colmap.sequential_overlap",
    "colmap.camera_model",
)
#: Đúng các khóa `estimate_gb` dùng: chỉ những thông số này được thu nhỏ theo máy. Thông số quyết định độ ổn định
#: (fps lấy mẫu, số ảnh lân cận, số bước huấn luyện, số vòng nén) không bao giờ bị hạ thầm.
RESOURCE_KEYS: tuple[str, ...] = (
    "sampling.max_frames",
    "colmap.max_image_size",
    "colmap.max_num_features",
    "brush.max_resolution",
    "brush.max_splats",
)
#: Nhóm thông số huấn luyện 3D Gaussian Splatting (chủ yếu quyết định VRAM).
SPLAT_KEYS: tuple[str, ...] = (
    "brush.total_train_iters",
    "brush.max_resolution",
    "brush.max_splats",
    "brush.sh_degree",
    "brush.sog_iterations",
)


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
    presets: ProcessingPresets,
    params: dict[str, ParamValue],
    capability: MachineCapability | None,
    observed: dict[Literal["vram", "ram"], float] | None = None,
) -> Evaluation:
    """So ước lượng với máy worker; ô thông số gây đỏ/vàng được đánh dấu tương ứng."""
    model = presets.resource_model
    values = presets.validate_params(params)
    required = estimate_gb(model, values)
    if observed is not None:
        if "vram" in observed:
            required["vram"] = observed["vram"]
        if "ram" in observed:
            required["ram"] = observed["ram"]
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
            prefix = "Đã đo ở lượt chạy trước" if (observed is not None and resource in observed) else "Cần khoảng"
            message = f"{prefix} {required[resource]:.1f} GB / máy có {have:.1f} GB {_LABEL[resource]}"
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
    """Nội suy tuyến tính các thông số số giữa hai bộ giá trị và làm tròn theo step. Thông số choice giữ theo `low`."""
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


def _fits(
    model: ResourceModel,
    values: dict[str, ParamValue],
    available: dict[Resource, float | None],
    resources: tuple[Resource, ...] | None = None,
) -> bool:
    required = estimate_gb(model, values)
    checked = resources if resources is not None else ("vram", "ram", "disk")
    return all(available.get(name) is None or required[name] < available[name] * model.warn_ratio for name in checked)


def resource_budget(capability: MachineCapability) -> dict[Resource, float | None] | None:
    """Ngân sách để thu nhỏ cấu hình: mốc "máy rảnh" nếu worker đã đo, không thì tổng năng lực máy.

    Không theo phần trống tức thời: lúc worker đang chạy job khác, phần trống đã bị chính job đó chiếm và sẽ được
    trả lại trước khi job mới chạy (job mới chờ trong hàng đợi với nguyên cấu hình). Mốc rảnh thiếu số đo RAM/VRAM
    → None: không suy ngân sách từ số đo thiếu.
    """
    idle = _idle(capability)
    if idle is not None:
        return None if any(value is None for value in idle.values()) else idle
    return {"vram": capability.vram_total_gb, "ram": capability.ram_total_gb, "disk": capability.disk_free_gb}


def fit_to_budget(
    presets: ProcessingPresets,
    floor: dict[str, ParamValue],
    target: dict[str, ParamValue],
    available: dict[Resource, float | None],
) -> tuple[dict[str, ParamValue], float] | None:
    """Một lần chia đôi chung cho cả năm khóa tài nguyên với cùng `t` giữa sàn và mục tiêu.

    Chỉ `RESOURCE_KEYS` đổi; mọi khóa khác giữ nguyên giá trị mục tiêu. Trả (bộ thông số, t) với t = 1 khi mục tiêu
    vừa máy; None khi ngay cả sàn cũng không vừa (dưới ngưỡng vàng của mọi tài nguyên đã đo).
    """
    model = presets.resource_model

    def candidate(t: float) -> dict[str, ParamValue]:
        interp = interpolate(presets, floor, target, t)
        values = dict(target)
        for key in RESOURCE_KEYS:
            values[key] = interp[key]
        return values

    if _fits(model, target, available):
        return dict(target), 1.0
    best = candidate(0.0)
    if not _fits(model, best, available):
        return None
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        values = candidate(mid)
        if _fits(model, values, available):
            best, lo = values, mid
        else:
            hi = mid
    return best, lo


def maximum_for_machine(presets: ProcessingPresets, capability: MachineCapability | None) -> dict[str, ParamValue]:
    """Preset `maximum` thu nhỏ theo máy bằng cùng bộ chia đôi của bộ gợi ý (sàn = preset tối thiểu).

    Không có số đo máy, mốc rảnh thiếu số đo, hoặc ngay cả sàn cũng không vừa → preset tối thiểu (không đoán);
    bảng thông số sẽ tô đỏ theo ước lượng.
    """
    minimum = dict(presets.presets["minimum_quality"])
    if capability is None:
        return minimum
    available = resource_budget(capability)
    if available is None:
        return minimum
    target = dict(presets.presets["maximum"])
    floor = dict(target) | {key: min(minimum[key], target[key], key=float) for key in RESOURCE_KEYS}
    fitted = fit_to_budget(presets, floor, target, available)
    return presets.validate_params(fitted[0]) if fitted is not None else minimum
