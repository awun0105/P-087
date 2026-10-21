"""Bộ gợi ý cấu hình: kịch bản người dùng chọn + sự thật của video + sự thật của worker (T-071).

Thứ tự tính cố định (mỗi bước ghi `notes` để giao diện nói thẳng với người dùng):
1. chọn catalog entry; 2. override theo kịch bản; 3. mức "chất lượng cao hơn"; 4. theo worker (từ điển khép vòng);
5. theo video (thời lượng, độ phân giải); 6. thu nhỏ theo tài nguyên đã đo của máy xử lý.
"""

import math
from dataclasses import dataclass, field
from typing import Literal

from src.services.orchestration.processing.models import (
    MachineCapability,
    ParameterSpec,
    ParamValue,
    ProcessingPresets,
    ScenarioPreferences,
)
from src.services.orchestration.processing.resources import (
    RESOURCE_KEYS,
    Resource,
    estimate_gb,
    fit_to_budget,
    resource_budget,
)

CapacityTarget = Literal["standard", "high_quality"]

#: Số giây video mà cửa sổ ghép ảnh liên tiếp cần phủ khi phải lấy thưa frame (theo kịch bản).
OVERLAP_SECONDS: dict[str, float] = {
    "video_indoor_walkthrough": 5,
    "video_indoor_orbital_360": 7,
    "video_single_object": 7,
    "video_outdoor_forward": 4,
}
#: Video ngắn vẫn cần đủ ảnh để COLMAP khởi tạo; dưới mức này không thu nhỏ thêm.
MIN_VIDEO_FRAMES = 60
MAX_SEQUENTIAL_OVERLAP = 30
#: Mức "chất lượng cao hơn": hệ số nhân và trần (None = trần của schema). Viewer cảnh báo trên vài triệu Gaussian.
HIGH_QUALITY_SCALE: dict[str, tuple[float, float | None]] = {
    "sampling.max_frames": (1.5, None),
    "colmap.max_num_features": (1.5, 16_384),
    "brush.max_splats": (1.5, 4_000_000),
}
HIGH_QUALITY_EXTRA_ITERS = 10_000
#: Bộ ảnh lớn hơn mức này thì ghép mọi cặp mất nhiều giờ.
LARGE_PHOTO_SET = 300

_RESOURCE_LABEL: dict[Resource, str] = {"vram": "VRAM GPU", "ram": "RAM", "disk": "ổ đĩa"}


class RecommendationUnavailableError(ValueError):
    """Even the declared minimum cannot fit the known worker resource budget."""


@dataclass(frozen=True)
class Recommendation:
    """Kết quả của bộ gợi ý: preset gốc, bộ thông số đã kiểm, ghi chú cho người dùng và mã lùi về đường an toàn."""

    name: str
    params: dict[str, ParamValue]
    notes: list[str] = field(default_factory=list)
    #: Mã máy đọc được, ví dụ `vocab_tree_unavailable`, `capability_unknown`, `machine_limited` (cho log và test).
    fallbacks: list[str] = field(default_factory=list)


def select_preset_name(preferences: ScenarioPreferences) -> str:
    """Photo capture takes precedence; video object scans share one scenario preset."""
    if preferences.input_type == "photo_set":
        return f"photo_collection_{preferences.environment}"
    if preferences.subject_scope == "single_object":
        return "video_single_object"
    if preferences.environment == "outdoor":
        return "video_outdoor_forward"
    return "video_indoor_orbital_360" if preferences.input_type == "video_loop_360" else "video_indoor_walkthrough"


def _on_grid(spec: ParameterSpec, value: float, *, up: bool) -> ParamValue:
    """Làm tròn lên/xuống theo lưới `min + k × step` của schema rồi kẹp trong [min, max]."""
    minimum, maximum, step = float(spec.min or 0), float(spec.max or value), float(spec.step or 1)
    steps = (value - minimum) / step
    snapped = minimum + (math.ceil(steps - 1e-9) if up else math.floor(steps + 1e-9)) * step
    snapped = max(minimum, min(maximum, snapped))
    return int(round(snapped)) if spec.kind == "integer" else round(snapped, 4)


def _number(value: ParamValue) -> str:
    """Số kiểu Việt Nam: dấu chấm ngăn nghìn."""
    return f"{int(value):,}".replace(",", ".") if isinstance(value, int) else str(value).replace(".", ",")


def _high_quality(values: dict[str, ParamValue], presets: ProcessingPresets) -> None:
    """Nhân các thông số chất lượng của kịch bản; không đụng fps, overlap, độ phân giải (đã kẹp theo video)."""
    for key, (factor, ceiling) in HIGH_QUALITY_SCALE.items():
        spec = presets.spec(key)
        wanted = float(values[key]) * factor
        if ceiling is not None:
            wanted = min(wanted, ceiling)
        values[key] = _on_grid(spec, wanted, up=False)
    spec = presets.spec("brush.total_train_iters")
    values["brush.total_train_iters"] = _on_grid(
        spec, float(values["brush.total_train_iters"]) + HIGH_QUALITY_EXTRA_ITERS, up=False
    )


def _apply_video(
    name: str, values: dict[str, ParamValue], preferences: ScenarioPreferences, presets: ProcessingPresets
) -> list[str]:
    """Số frame theo thời lượng thật, cửa sổ ghép ảnh theo giây khi phải lấy thưa, độ phân giải theo video."""
    video = preferences.video
    if video is None:
        return []
    notes: list[str] = []
    duration = video.duration_seconds
    cap = int(values["sampling.max_frames"])
    wanted = math.ceil(duration * float(values["sampling.sample_fps"]))
    frames_spec = presets.spec("sampling.max_frames")
    values["sampling.max_frames"] = min(cap, int(_on_grid(frames_spec, max(MIN_VIDEO_FRAMES, wanted), up=True)))
    if wanted > cap:
        effective = cap / duration
        minutes, seconds = divmod(round(duration), 60)
        fps = f"{effective:.1f}".replace(".", ",")
        notes.append(f"Video {minutes} phút {seconds} giây: lấy {fps} khung hình mỗi giây (tối đa {_number(cap)} ảnh)")
        window = OVERLAP_SECONDS.get(name)
        if window is not None:
            scenario = int(values["colmap.sequential_overlap"])
            values["colmap.sequential_overlap"] = min(
                MAX_SEQUENTIAL_OVERLAP, max(scenario, math.ceil(window * effective - 1e-9))
            )
    long_edge = max(video.display_width, video.display_height)
    lowered = False
    for key in ("colmap.max_image_size", "brush.max_resolution"):
        limit = _on_grid(presets.spec(key), long_edge, up=True)
        if float(limit) < float(values[key]):
            values[key] = limit
            lowered = True
    if lowered:
        notes.append(
            f"Video {video.display_width}×{video.display_height}: độ phân giải huấn luyện"
            f" {_number(values['brush.max_resolution'])} px"
        )
    return notes


def scale_for_machine(
    params: dict[str, ParamValue],
    capability: MachineCapability | None,
    *,
    presets: ProcessingPresets,
) -> tuple[dict[str, ParamValue], list[str]]:
    """Thu nhỏ đúng năm khóa tài nguyên bằng một lần chia đôi chung giữa sàn và cấu hình mục tiêu.

    Sàn = preset `minimum_quality` (nếu mục tiêu đã thấp hơn — ví dụ video ngắn, video 720p — thì sàn là chính mục
    tiêu). Không có số đo máy → trả sàn kèm ghi chú, không tự nhận là an toàn. Sàn không vừa → lỗi.
    """
    target = presets.validate_params(params)
    minimum = presets.presets["minimum_quality"]
    floor = dict(target) | {key: min(minimum[key], target[key], key=float) for key in RESOURCE_KEYS}
    if capability is None:
        return presets.validate_params(floor), ["Chưa có số đo máy xử lý; dùng mức an toàn"]
    if capability.vram_total_gb is None or capability.vram_total_gb <= 0:
        raise RecommendationUnavailableError("Máy xử lý chưa có GPU/VRAM phù hợp để dựng 3DGS.")
    available = resource_budget(capability)
    if available is None or any(value is None for value in available.values()):
        raise RecommendationUnavailableError("Số đo lúc máy xử lý rảnh còn thiếu; chưa gợi ý được cấu hình an toàn.")
    fitted = fit_to_budget(presets, floor, target, available)
    if fitted is None:
        raise RecommendationUnavailableError("Cấu hình thấp nhất vẫn vượt ngân sách tài nguyên đã đo của máy xử lý.")
    scaled, t = fitted
    notes: list[str] = []
    if t < 1:
        required = estimate_gb(presets.resource_model, target)
        limited = [
            _RESOURCE_LABEL[name]
            for name in ("vram", "ram", "disk")
            if (budget := available[name]) is not None and required[name] >= budget * presets.resource_model.warn_ratio
        ]
        for key in RESOURCE_KEYS:
            if scaled[key] != target[key]:
                spec = presets.spec(key)
                unit = f" {spec.unit}" if spec.unit else ""
                notes.append(
                    f"Máy xử lý giới hạn {', '.join(limited)}: giảm {spec.label.lower()} xuống"
                    f" {_number(scaled[key])}{unit}"
                )
    return presets.validate_params(scaled), notes


def recommend_preset(
    preferences: ScenarioPreferences, capability: MachineCapability | None, presets: ProcessingPresets
) -> Recommendation:
    """Select a catalog entry, apply scenario/worker/video facts, then scale numeric resource drivers."""
    name = select_preset_name(preferences)
    if name not in presets.presets:
        raise ValueError(f"scenario preset missing from catalog: {name}")
    values = dict(presets.presets[name])
    single = preferences.subject_scope == "single_object"
    indoor = preferences.environment == "indoor"
    # Video liên tục giữ cách ghép của kịch bản (đi bộ trong nhà dùng khép vòng); quay vòng luôn cần khép vòng.
    matching = (
        "exhaustive"
        if preferences.input_type == "photo_set"
        else "sequential_vocab_tree"
        if preferences.input_type == "video_loop_360"
        else values.get("colmap.matching_mode", "sequential")
    )
    overrides = {
        "colmap.matching_mode": matching,
        "scene.max_objects": 1 if single else values.get("scene.max_objects", 60),
        "geometry.external_fill_size_m": 1.6 if indoor and not single else 0,
        "geometry.floor_fill_size_m": 1.6 if not indoor and not single else 0,
        "simulation.ground_plane": "enabled" if indoor else "disabled",
    }
    values.update({key: value for key, value in overrides.items() if key in values})
    notes: list[str] = []
    fallbacks: list[str] = []
    if preferences.target_capacity == "high_quality":
        _high_quality(values, presets)
    if values.get("colmap.matching_mode") == "sequential_vocab_tree" and (
        capability is None or capability.colmap_vocab_tree_available is not True
    ):
        values["colmap.matching_mode"] = "sequential"
        fallbacks.append("vocab_tree_unavailable")
        notes.append(
            "Máy xử lý chưa có từ điển khép vòng; dùng ghép liên tiếp, thang thử lại sẽ dùng ghép mọi cặp nếu đứt chuỗi"
        )
    if preferences.input_type != "photo_set":
        notes.extend(_apply_video(name, values, preferences, presets))
    elif preferences.photo_count is not None and preferences.photo_count > LARGE_PHOTO_SET:
        notes.append(
            f"Bộ ảnh {_number(preferences.photo_count)} ảnh: ghép mọi cặp sẽ mất nhiều giờ; nên dưới {LARGE_PHOTO_SET} ảnh"
        )
    params, machine_notes = scale_for_machine(values, capability, presets=presets)
    if capability is None:
        fallbacks.append("capability_unknown")
    elif machine_notes:
        fallbacks.append("machine_limited")
    return Recommendation(name=name, params=params, notes=notes + machine_notes, fallbacks=fallbacks)
