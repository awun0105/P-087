"""EX-REC reconstruction service boundary."""

# Lazy import giữ API/storage process không kéo native reconstruction dependencies.
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.preview import PreviewWorkerReceipt

if TYPE_CHECKING:
    from src.services.reconstruction.metric_port import UserMetricPort


def verify_prepared_preview(
    reference: ProductArtifactRef, resolve: Callable[[ProductArtifactRef], Path]
) -> PreviewWorkerReceipt:
    """Public read-only port, không yêu cầu PRODUCT import module nội bộ REC."""
    from src.services.reconstruction.ports import verify_prepared_preview as verify

    return verify(reference, resolve)


def user_metric_port(
    resolve: Callable[[ProductArtifactRef], Path],
    writer: object,
    exists: Callable[[str], bool],
) -> "UserMetricPort":
    """Public port REC-06: xem trước/xác nhận tỉ lệ mét từ điểm người dùng chọn."""
    from src.services.reconstruction.metric_port import UserMetricPort as Port

    return Port(resolve, writer, exists)  # type: ignore[arg-type]


def __getattr__(name: str) -> object:
    """Model public của port REC-06 / nhận diện đầu vào (import lười để API không kéo module REC khi không dùng)."""
    if name in {
        "UserMetricInput",
        "UserMetricPreview",
        "UserMetricPort",
        "LidarMeasurements",
        "DemoSelection",
        "ModeComparison",
        "check_tolerance_m",
        "publish_json",
    }:
        from src.services.reconstruction import metric_port

        return getattr(metric_port, name)
    if name in {
        "ConfirmationSummary",
        "FinalizeRequest",
        "FinalizeResult",
        "GeometryProfile",
        "confirmation_summary",
        "load_finalize_result",
        "load_geometry_profile",
    }:
        from src.services.reconstruction import finalize

        return getattr(finalize, name)
    if name in {"CameraMarker", "camera_markers", "frame_images"}:
        from src.services.reconstruction import views

        return getattr(views, name)
    if name in {"extract_member", "package_splat"}:
        from src.services.reconstruction import imports

        return getattr(imports, name)
    if name == "lidar_support_uri":
        from src.services.reconstruction.rgb.canonical.lidar_assist import support_uri

        return support_uri
    if name in {"detect_input", "detect_stream", "InputDetection", "InputKind", "InputRejectedError"}:
        from src.services.reconstruction.inputs import detect

        return getattr(detect, name)
    raise AttributeError(name)


__all__ = [
    "extract_member",
    "package_splat",
    "ModeComparison",
    "CameraMarker",
    "camera_markers",
    "frame_images",
    "ConfirmationSummary",
    "FinalizeRequest",
    "FinalizeResult",
    "GeometryProfile",
    "confirmation_summary",
    "load_finalize_result",
    "load_geometry_profile",
    "DemoSelection",
    "InputDetection",
    "InputKind",
    "InputRejectedError",
    "LidarMeasurements",
    "UserMetricInput",
    "UserMetricPort",
    "UserMetricPreview",
    "check_tolerance_m",
    "detect_input",
    "detect_stream",
    "lidar_support_uri",
    "publish_json",
    "user_metric_port",
    "verify_prepared_preview",
]
