"""Lấy mẫu và lưu bản ghi tài nguyên, dùng chung cho runner và hàng đợi tách vật."""

import logging
from pathlib import Path
from uuid import uuid4

from src.config import Settings
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing import is_presets_file, load_presets
from src.services.orchestration.processing.capability import measure_capacity
from src.services.orchestration.processing.telemetry import ResourceContext, ResourceSampler, ResourceUsage

logger = logging.getLogger(__name__)


def build_sampler(settings: Settings, context: ResourceContext, workspace: Path) -> ResourceSampler | None:
    """Sampler cho một lượt chạy; lỗi khi dựng trả None, không làm hỏng việc chạy."""
    try:
        ratio: float | None = None
        path = settings.product_processing_config
        if path is not None and is_presets_file(path):
            ratio = load_presets(path)[0].resource_model.danger_ratio
        return ResourceSampler(
            context,
            workspace=workspace,
            worker_root=settings.product_worker_root,
            exhaustion_ratio=ratio,
            ram_total_gb=measure_capacity(settings.product_worker_root)["ram"],
        )
    except Exception as error:  # noqa: BLE001 - measurement boundary must not change job execution
        logger.warning("Không tạo được resource sampler cause=%s", type(error).__name__)
        return None


def record_usage(database: RuntimeDatabase, usage: ResourceUsage) -> None:
    """Lưu bản ghi vào runtime DB: đĩa của máy GPU thuê mất khi trả máy, DB thì không."""
    try:
        with database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_resource_usage(usage_id,job_id,recorded_at,payload) VALUES (?,?,?,?)",
                (uuid4().hex, usage.job_id, usage.completed_at.isoformat(), usage.model_dump_json()),
            )
    except Exception as error:  # noqa: BLE001 - ranh giới DB của số đo: không đổi kết quả job
        logger.warning("Không lưu được resource telemetry vào DB cause=%s", type(error).__name__)
