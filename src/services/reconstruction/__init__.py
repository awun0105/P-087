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
    """Model public của port REC-06 (import lười để API không kéo module REC khi không dùng)."""
    if name in {"UserMetricInput", "UserMetricPreview", "UserMetricPort", "publish_json"}:
        from src.services.reconstruction import metric_port

        return getattr(metric_port, name)
    raise AttributeError(name)


__all__ = [
    "UserMetricInput",
    "UserMetricPort",
    "UserMetricPreview",
    "publish_json",
    "user_metric_port",
    "verify_prepared_preview",
]
