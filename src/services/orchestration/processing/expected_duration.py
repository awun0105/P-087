"""Thời gian kỳ vọng của một công cụ theo khối lượng scene (T-043 bước 4).

Hàm thuần: lấy các lượt đo đã hoàn tất cùng công cụ và cùng GPU, quy về giây trên một đơn vị khối lượng, rồi nhân với khối
lượng của job. Dùng làm hạn tự tính thay cho một con số cố định; thiếu số đo thì không trả ước lượng nào.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from src.services.orchestration.processing.telemetry import ResourceUsage

#: Khoá khối lượng (đúng tên trong preset) cho từng công cụ. Công cụ không có khoá thì không ước được.
#: `preview` gộp COLMAP và Brush: Brush theo vòng huấn luyện là phần chiếm chính, COLMAP theo ảnh nằm trong cùng lượt.
WORK_UNIT_KEYS: dict[str, str] = {
    "preview": "brush.total_train_iters",
    "finalize": "scene.objectgs_iterations",
    "scene_extract": "scene.objectgs_iterations",
    "prepare": "sampling.max_frames",
    "metric_proposal": "sampling.max_frames",
    "lidar_ingest": "sampling.max_frames",
    "lidar_calibration_qa": "sampling.max_frames",
    "lidar_odometry": "sampling.max_frames",
}
#: Số lượt đo tối thiểu để tin một ước lượng.
MIN_SAMPLES = 3
#: Sàn của hạn tự tính: không bao giờ dưới mức này, kể cả khi scene nhỏ.
FLOOR_SECONDS = 600.0
#: Hệ số trên ước lượng: lượt chạy chậm gấp ba so với thường thấy được coi là treo.
SAFETY_FACTOR = 3.0


@dataclass(frozen=True)
class Estimate:
    """Ước lượng cho một lượt chạy công cụ; ghi vào log của lượt chạy và vào lỗi khi hết hạn."""

    tool: str
    seconds: float
    seconds_per_unit: float
    units: float
    samples: int
    gpu_name: str
    scope: Literal["cùng runtime", "cùng GPU"]


def expected_seconds(
    tool: str,
    params: Mapping[str, float],
    gpu_name: str | None,
    runtime_manifest_checksum: str | None,
    usages: Iterable[ResourceUsage],
) -> Estimate | None:
    """Ước thời gian của `tool` cho khối lượng `params` trên `gpu_name`; None nếu không đủ dữ liệu."""
    key = WORK_UNIT_KEYS.get(tool)
    if key is None or gpu_name is None:
        return None
    units = params.get(key)
    if units is None or units <= 0:
        return None
    matched = [
        usage
        for usage in usages
        if usage.tool == tool
        and usage.outcome == "completed"
        and usage.gpu_name == gpu_name
        and usage.params is not None
        and usage.params.get(key, 0) > 0
        and usage.duration_seconds > 0
    ]
    same_runtime = [usage for usage in matched if usage.runtime_manifest_checksum == runtime_manifest_checksum]
    if len(same_runtime) >= MIN_SAMPLES:
        pool, scope = same_runtime, "cùng runtime"
    else:
        pool, scope = matched, "cùng GPU"
    if len(pool) < MIN_SAMPLES:
        return None
    per_unit = statistics.median(usage.duration_seconds / usage.params[key] for usage in pool)  # type: ignore[index]
    return Estimate(
        tool=tool,
        seconds=per_unit * units,
        seconds_per_unit=per_unit,
        units=units,
        samples=len(pool),
        gpu_name=gpu_name,
        scope=scope,
    )


def deadline_seconds(estimate: Estimate, fixed_limit: float) -> float:
    """Hạn dùng = max(sàn, hệ số × ước), không vượt giới hạn cố định hiện có."""
    return min(fixed_limit, max(FLOOR_SECONDS, SAFETY_FACTOR * estimate.seconds))
