"""Bước hoàn tất chỉ gắn LiDAR vào bundle khi người dùng đã xác nhận tỉ lệ từ căn chỉnh quỹ đạo (ADR 0009)."""

from types import SimpleNamespace

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.services.reconstruction.finalize import FinalizeRequest, FinalizeWorker

_PACKAGE = ProductArtifactRef(
    artifact_type="LidarPackageRecord",
    schema_version="1.0",
    artifact_uri="artifact://jobs/job-a/rec08/x/lidar_package.json",
    artifact_checksum="sha256:" + "1" * 64,
    data_class="derived",
    producer_stage=StageId.LIDAR_INGEST,
    job_id="job-a",
)


def _worker() -> FinalizeWorker:
    worker = FinalizeWorker.__new__(FinalizeWorker)

    def unreachable(_reference: ProductArtifactRef) -> None:
        raise AssertionError("không được đọc artifact LiDAR khi không gắn LiDAR vào bundle")

    worker.visuals = SimpleNamespace(require=unreachable)  # type: ignore[assignment]
    return worker


@pytest.mark.parametrize(
    ("package", "source"),
    [(None, "lidar_trajectory"), (_PACKAGE, "user_measured"), (_PACKAGE, "ai_estimated")],
)
def test_bundle_stays_rgb_only_without_a_confirmed_trajectory_alignment(
    package: ProductArtifactRef | None, source: str
) -> None:
    request = FinalizeRequest.model_construct(job_id="job-a", attempt_id="finalize-1", lidar_package_ref=package)
    assert _worker()._lidar_alignment(request, SimpleNamespace(), source) is None  # type: ignore[arg-type]


def test_finalize_request_accepts_the_lidar_package_and_defaults_to_video_only() -> None:
    fields = FinalizeRequest.model_fields
    assert fields["lidar_package_ref"].default is None
