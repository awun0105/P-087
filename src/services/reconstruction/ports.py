"""Public consumer port REC→PRODUCT; không khởi tạo hay chạy reconstruction tools."""

from collections.abc import Callable
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.preview import PreviewWorkerReceipt
from src.services.reconstruction.preview_validation import PreviewReadDependencies, load_preview
from src.services.reconstruction.rgb.frame_set import FrameSetResolver


def verify_prepared_preview(
    reference: ProductArtifactRef, resolve: Callable[[ProductArtifactRef], Path]
) -> PreviewWorkerReceipt:
    """Đọc published result và kiểm toàn graph; không tin stdout SUCCESS của process."""
    result = load_preview(reference, PreviewReadDependencies(FrameSetResolver(resolve, resolve), resolve))
    if result.preview_complete and result.preview_ref is None:
        raise ValueError("Legacy preview thiếu shared preview publication; cần attempt mới")
    return PreviewWorkerReceipt(
        job_id=result.job_id,
        attempt_id=result.attempt_id,
        source_input_checksum=result.source_input_checksum,
        result_ref=reference,
        stage_artifacts=result.stage_artifacts,
        preview_ref=result.preview_ref,
        error=result.error,
    )
