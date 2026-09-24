"""Product-level models cho vòng đời job (PRODUCT-02).

Không phải shared contract: `JobManifest` đã là contract chung và không có field
attempt. Lịch sử attempt là khái niệm product, nên nằm ở đây.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.artifacts import ArtifactUri, Checksum, Identifier
from src.models.contracts.manifests import ExecutionError, JobStatus, StageId


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
