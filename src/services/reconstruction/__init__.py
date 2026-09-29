"""EX-REC reconstruction service boundary."""

# Lazy import giữ API/storage process không kéo native reconstruction dependencies.
from collections.abc import Callable
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.preview import PreviewWorkerReceipt


def verify_prepared_preview(
    reference: ProductArtifactRef, resolve: Callable[[ProductArtifactRef], Path]
) -> PreviewWorkerReceipt:
    """Public read-only port, không yêu cầu PRODUCT import module nội bộ REC."""
    from src.services.reconstruction.ports import verify_prepared_preview as verify

    return verify(reference, resolve)


__all__ = ["verify_prepared_preview"]
