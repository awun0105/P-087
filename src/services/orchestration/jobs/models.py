"""Product-level models cho vòng đời job (PRODUCT-02).

Không phải shared contract: `JobManifest` đã là contract chung và không có field
attempt. Lịch sử attempt là khái niệm product, nên nằm ở đây.
"""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.contracts.artifacts import ArtifactUri, Checksum, Identifier, ProductArtifactRef
from src.models.contracts.manifests import ExecutionError, JobStatus, StageArtifact, StageId, StageStatus


class JobAttemptRecord(BaseModel):
    """Một lần chạy của job.

    Retry **nối thêm** record mới, không sửa record cũ — provenance của attempt đã
    hỏng phải còn đọc được.
    """

    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    status: JobStatus
    current_stage: StageId
    recorded_at: datetime
    job_manifest_uri: ArtifactUri | None = None
    job_manifest_checksum: Checksum | None = None
    error: ExecutionError | None = None
    actual_frame_count: int | None = Field(default=None, ge=2)
    stage_started_at: datetime | None = None
    preview_verified_at: datetime | None = None


class TransitionRequest(BaseModel):
    """Yêu cầu chuyển trạng thái job."""

    model_config = ConfigDict(extra="forbid")

    target_status: JobStatus
    current_stage: StageId | None = None
    error: ExecutionError | None = None


class JobDetail(BaseModel):
    """Job kèm lịch sử attempt để UI hiển thị."""

    model_config = ConfigDict(extra="forbid")

    job_id: Identifier
    attempts: list[JobAttemptRecord]


class PreparedInputReceipt(BaseModel):
    """Phần PRODUCT đọc từ kết quả `prepare` của EX-REC, chỉ qua shared contracts.

    PRODUCT chỉ nhận số frame thực tế cần cho benchmark; các chi tiết chuẩn bị
    nội bộ khác như stride vẫn thuộc EX-REC.
    """

    model_config = ConfigDict(extra="ignore")

    job_id: Identifier
    input_manifest_checksum: Checksum
    stage_artifacts: list[StageArtifact]
    frame_set_ref: ProductArtifactRef | None = None
    extracted_frame_count: int | None = Field(default=None, ge=2)
    error: ExecutionError | None = None

    @model_validator(mode="after")
    def _outcome(self) -> Self:
        if (self.error is None) == (self.frame_set_ref is None):
            raise ValueError("prepare receipt cần đúng một trong frame_set_ref hoặc error")
        if self.frame_set_ref is not None:
            frames = [
                stage
                for stage in self.stage_artifacts
                if stage.stage_id == StageId.FRAME_EXTRACT and stage.status == StageStatus.SUCCEEDED
            ]
            if len(frames) != 1 or frames[0].artifact_uri != self.frame_set_ref.artifact_uri:
                raise ValueError("frame_set_ref phải khớp stage ST-FRAME-EXTRACT đã SUCCEEDED")
            if frames[0].artifact_checksum != self.frame_set_ref.artifact_checksum:
                raise ValueError("frame_set_ref checksum khác stage record")
        return self
