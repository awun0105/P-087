"""Người dùng xem các frame đã che rồi chấp nhận, trước khi job dựng 3D (AUD-18, ADR 0019).

Nguồn sự thật là frame set đã che mà stage `ST-FRAME-EXTRACT` của job trỏ tới. Manifest che được đối chiếu với
checksum ghi trong chính frame set đó, nên API không tin một manifest lạ đặt cùng thư mục. Chấp nhận ghi một
artifact bất biến gắn với đúng frame set người dùng đã xem; từ chối là hủy job bằng route hủy sẵn có.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import JobManifest, StageId
from src.models.contracts.sanitization import SanitizationManifest
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs.database import RuntimeStateConflictError
from src.services.orchestration.jobs.progress import (
    ANONYMIZATION_ACCEPTANCE_TYPE,
    anonymization_acceptance_stage,
    awaiting_anonymization_review,
    sanitized_frame_stage,
)
from src.services.orchestration.projects import ProjectRegistry
from src.services.reconstruction.rgb.frames.frame_set import NormalizedRGBFrameSet

_FRAMES = "/rec02a/sanitized/frames/"


class AnonymizationReviewError(ValueError):
    """Job không có bản đã che để xem, hoặc dữ liệu che không khớp nhau."""


class ReviewRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    #: Hộp đã tô (x1, y1, x2, y2) theo pixel của frame.
    box: tuple[int, int, int, int]


class ReviewFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_name: str
    width: int
    height: int
    regions: list[ReviewRegion]


class AnonymizationReview(BaseModel):
    """Dữ liệu cho màn xem bản đã che. `frames` chỉ gồm frame có vùng bị che."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["awaiting", "accepted", "closed"]
    frame_set_checksum: str
    frame_count: int
    frames: list[ReviewFrame]


class SanitizationAcceptance(BaseModel):
    """Bản ghi bất biến: ai đã chấp nhận bản đã che nào."""

    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["SanitizationAcceptance"] = ANONYMIZATION_ACCEPTANCE_TYPE
    schema_version: Literal["1.0"] = "1.0"
    job_id: str
    frame_set_checksum: str
    sanitization_manifest_checksum: str
    redacted_frame_count: int
    accepted_by: str | None
    accepted_at: datetime


def _load(registry: ProjectRegistry, job: JobManifest) -> tuple[NormalizedRGBFrameSet, SanitizationManifest]:
    stage = sanitized_frame_stage(job)
    if stage is None or stage.artifact_uri is None or stage.artifact_checksum is None:
        raise AnonymizationReviewError("Job này không có bước che khuôn mặt/biển số")
    resolver = registry.runtime_resolver
    frame_set = NormalizedRGBFrameSet.model_validate_json(
        resolver.require_uri(stage.artifact_uri, stage.artifact_checksum).read_bytes()
    )
    manifest_path = resolver.locate(stage.artifact_uri.rsplit("/", 1)[0] + "/manifest.json")
    if manifest_path is None:
        raise AnonymizationReviewError("Thiếu bản kê các vùng đã che của job")
    manifest = SanitizationManifest.model_validate_json(manifest_path.read_bytes())
    # File manifest không nằm trong stage artifact của job nên không có checksum byte để đối chiếu: tính lại
    # checksum nội dung rồi so với giá trị frame set đã ghi.
    if (
        canonical_content_checksum(manifest, "manifest_checksum") != manifest.manifest_checksum
        or manifest.manifest_checksum != frame_set.sanitization_manifest_checksum
    ):
        raise AnonymizationReviewError("Bản kê các vùng đã che không khớp bộ frame của job")
    return frame_set, manifest


def review(registry: ProjectRegistry, job_id: str) -> AnonymizationReview:
    job = registry.get_job(job_id)
    frame_set, manifest = _load(registry, job)
    if awaiting_anonymization_review(job):
        state: Literal["awaiting", "accepted", "closed"] = "awaiting"
    else:
        state = "accepted" if anonymization_acceptance_stage(job) is not None else "closed"
    return AnonymizationReview(
        state=state,
        frame_set_checksum=frame_set.frame_set_checksum,
        frame_count=len(frame_set.frames),
        frames=[
            ReviewFrame(
                frame_name=frame.frame_name,
                width=frame.width,
                height=frame.height,
                regions=[ReviewRegion(kind=region.kind, box=region.applied_box) for region in frame.regions],
            )
            for frame in manifest.frames
            if frame.regions
        ],
    )


def redacted_frame(registry: ProjectRegistry, job_id: str, frame_name: str) -> ProductArtifactRef:
    """Ref của một frame đã che thuộc đúng frame set của job; tên lạ không resolve ra file nào."""
    frame_set, _ = _load(registry, registry.get_job(job_id))
    suffix = _FRAMES + frame_name
    for frame in frame_set.frames:
        if frame.image.job_id == job_id and frame.image.artifact_uri.endswith(suffix):
            return frame.image
    raise AnonymizationReviewError("Frame này không nằm trong bản đã che của job")


def accept(registry: ProjectRegistry, job_id: str, frame_set_checksum: str, user_id: str | None) -> ProductArtifactRef:
    """Chấp nhận đúng bộ frame đã xem; job được worker nhận lại để dựng 3D."""
    job = registry.get_job(job_id)
    if not awaiting_anonymization_review(job):
        raise RuntimeStateConflictError("Job không ở bước chờ xem bản đã che")
    frame_set, manifest = _load(registry, job)
    if frame_set_checksum != frame_set.frame_set_checksum:
        raise RuntimeStateConflictError("Bản đã che đã thay đổi sau khi bạn xem; tải lại rồi xác nhận")
    record = SanitizationAcceptance(
        job_id=job_id,
        frame_set_checksum=frame_set.frame_set_checksum,
        sanitization_manifest_checksum=manifest.manifest_checksum,
        redacted_frame_count=sum(1 for frame in manifest.frames if frame.regions),
        accepted_by=user_id,
        accepted_at=datetime.now(UTC),
    )
    payload = record.model_dump_json(indent=2).encode() + b"\n"
    reference = ProductArtifactRef(
        artifact_type=ANONYMIZATION_ACCEPTANCE_TYPE,
        schema_version="1.0",
        # Một attempt chỉ có một frame set đã che; checksum trong tên để lần chạy lại không đụng bản ghi cũ.
        artifact_uri=f"artifact://jobs/{job_id}/rec02a/sanitized/acceptance-{frame_set.frame_set_checksum[7:23]}.json",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.PRIVACY_GATE,
        job_id=job_id,
    )
    published = ProductArtifactRef.model_validate(
        FilesystemArtifactStore(registry.runtime_resolver).publish(reference, payload).model_dump()
    )
    registry.record_anonymization_acceptance(job, published)
    return published
