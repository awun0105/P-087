"""Admission theo live headroom: giữ config, chờ và tự dispatch khi đủ tài nguyên.

Observation trong DB chỉ giải thích vì sao chờ, bind manifest checksum. Durable
queue/lifecycle vẫn là JobManifest, không tạo attempt/revision khi poll tài nguyên.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from src.config import Settings
from src.models.contracts.manifests import JobManifest
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing import (
    JobProcessingConfig,
    is_presets_file,
    job_config_reference,
    load_presets,
)
from src.services.orchestration.processing.capability import measure_live_headroom
from src.services.orchestration.processing.resources import estimate_gb

if TYPE_CHECKING:
    from src.services.orchestration.projects.registry import ProjectRegistry

logger = logging.getLogger(__name__)
Resource = Literal["vram", "ram", "disk"]


class ResourceWait(BaseModel):
    """Snapshot chờ của đúng job revision, không chứa path hoặc secret."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    job_manifest_checksum: str
    checked_at: datetime
    required_gb: dict[Resource, float]
    available_gb: dict[Resource, float | None]
    waiting_on: list[Resource]
    estimate_scope: Literal["configured_preview"] = "configured_preview"


def resource_wait(database: RuntimeDatabase, job: JobManifest) -> ResourceWait | None:
    """Bỏ observation stale/revision khác; không sửa job khi API đọc tiến trình."""
    with database.transaction() as tx:
        row = tx.execute("SELECT payload FROM r2s_resource_waits WHERE job_id=?", (job.job_id,)).fetchone()
    if row is None:
        return None
    wait = ResourceWait.model_validate_json(row[0])
    if wait.job_manifest_checksum != job.job_manifest_checksum or datetime.now(UTC) - wait.checked_at > timedelta(
        minutes=15
    ):
        return None
    return wait


class ResourceAdmission:
    """Gate basic worker theo model config hiện có; không hạ cấu hình hoặc reserve GPU."""

    def __init__(self, registry: ProjectRegistry, settings: Settings) -> None:
        if registry.persistence is None:
            raise ValueError("Resource admission cần durable registry")
        self.registry = registry
        self.settings = settings
        self.database = registry.persistence.database
        settings.product_worker_root.mkdir(parents=True, exist_ok=True)

    def __call__(self, job: JobManifest) -> bool:
        """True khi đủ headroom; thiếu/unknown giữ nguyên queue/config và ghi diagnostic."""
        path = self.settings.product_processing_config
        profile = self.registry.execution_profile
        if (
            path is None
            or profile is None
            or job.config_checksum == profile.config_checksum
            or not is_presets_file(path)
        ):
            # Legacy tool profile chưa có resource model; không bịa yêu cầu tối thiểu.
            logger.info("Resource admission chưa có estimate cho legacy profile")
            return True
        presets, _ = load_presets(path)
        config_path = self.registry.runtime_resolver.require(job_config_reference(job.job_id, job.config_checksum))
        config = JobProcessingConfig.model_validate_json(config_path.read_bytes())
        required = estimate_gb(presets.resource_model, presets.validate_params(config.params))
        live = measure_live_headroom(self.settings.product_worker_root)
        available: dict[Resource, float | None] = {
            "vram": live["vram_free_gb"],
            "ram": live["ram_available_gb"],
            "disk": live["disk_free_gb"],
        }
        waiting: list[Resource] = [
            name
            for name in ("vram", "ram", "disk")
            if available[name] is None or required[name] >= available[name] * presets.resource_model.danger_ratio
        ]
        with self.database.transaction(write=True) as tx:
            if waiting:
                observation = ResourceWait(
                    job_manifest_checksum=job.job_manifest_checksum,
                    checked_at=datetime.now(UTC),
                    required_gb=required,
                    available_gb=available,
                    waiting_on=waiting,
                )
                tx.execute(
                    "INSERT INTO r2s_resource_waits(job_id,payload) VALUES (?,?) "
                    "ON CONFLICT(job_id) DO UPDATE SET payload=excluded.payload",
                    (job.job_id, observation.model_dump_json()),
                )
            else:
                tx.execute("DELETE FROM r2s_resource_waits WHERE job_id=?", (job.job_id,))
        return not waiting
