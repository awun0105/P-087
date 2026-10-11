"""Khoảng tham chiếu từ các scene đã chạy thành công trong repo."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)


class ReferenceScene(BaseModel):
    """Một scene chuẩn trong tập tham chiếu."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    job_id: str
    source: str
    psnr: float | None = None
    ssim: float | None = None
    lpips: float | None = None


class ReferenceSet(BaseModel):
    """Tập scene tham chiếu đọc từ configs/product/evaluation_reference_v1.json."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: Literal["1.0"] = "1.0"
    note: str
    scenes: list[ReferenceScene]


def load_reference(path: Path | None) -> ReferenceSet | None:
    """Nạp file tham chiếu; trả None khi thiếu file hoặc sai định dạng (không ném lỗi)."""
    if path is None:
        return None
    try:
        if not path.is_file():
            logger.warning("File tham chiếu đánh giá không tồn tại: %s", path)
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReferenceSet.model_validate(data)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
        logger.warning("Không đọc được file tham chiếu đánh giá %s: %s", path, error)
        return None


def describe(values: list[float], unit: str, digits: int) -> str | None:
    """Mô tả khoảng tham chiếu min–max và số lượng scene có giá trị. Trả None nếu < 2 giá trị."""
    if len(values) < 2:
        return None
    min_v = min(values)
    max_v = max(values)
    min_str = f"{min_v:.{digits}f}".replace(".", ",")
    max_str = f"{max_v:.{digits}f}".replace(".", ",")
    unit_str = f" {unit}" if unit else ""
    return f"Các scene đã chạy: {min_str}–{max_str}{unit_str} ({len(values)} scene)"
