"""Dựng SanitizationManifest từ kết quả của `anonymize_runner` (AUD-18)."""

from typing import Any

from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.sanitization import SanitizationManifest, SanitizedFrame, inventory_checksum

_PLACEHOLDER = "sha256:" + "0" * 64

#: Cấu hình mặc định. Hai ngưỡng và kích thước resize là giá trị Meta công bố cho camera RGB trong gói
#: `egoblur` 2.0.1 (`gen2/script/constants.py`); chưa được hiệu chỉnh trên video điện thoại hay biển số
#: Việt Nam vì chưa có dữ liệu đánh giá.
#:
#: Lan theo thời gian mặc định tắt (`propagate_radius = 0`). Frame đưa vào đây đã được lấy mẫu thưa (vài frame
#: mỗi giây) nên giữa hai frame liền nhau camera đã di chuyển: hộp chép từ frame bên cạnh không còn nằm trên đối
#: tượng, không che được gì mà lại thêm mảng đen sai chỗ vào ảnh train. Một lượt chạy trên frame thật
#: (2026-10-09) cho thấy một phát hiện nhầm (nhãn trắng trên thùng nhựa, điểm 0,839) bị nhân ra 5 frame.
DEFAULT_CONFIG: dict[str, Any] = {
    "face_threshold": 0.67416,
    "license_plate_threshold": 0.74475,
    "nms_iou": 0.5,
    "resize_short_edge": 1200,
    "resize_max": 1200,
    "expand_scale": 1.15,
    "propagate_radius": 0,
    "propagate_growth": 0.15,
    "fill_bgr": [0, 0, 0],
}


def manifest_from_runner_result(result: dict[str, Any], source_frame_set_checksum: str) -> SanitizationManifest:
    """Kiểm và đóng gói kết quả runner; kết quả thiếu frame hay lệch checksum bị từ chối ở đây."""
    frames = [SanitizedFrame.model_validate(frame) for frame in result["frames"]]
    draft = SanitizationManifest(
        source_frame_set_checksum=source_frame_set_checksum,
        detector=result["detector"],
        config=result["config"],
        requested_frame_count=result["requested_frame_count"],
        frames=frames,
        failures=result["failures"],
        sanitized_inventory_checksum=inventory_checksum(frames),
        manifest_checksum=_PLACEHOLDER,
    )
    return draft.model_copy(update={"manifest_checksum": canonical_content_checksum(draft, "manifest_checksum")})
