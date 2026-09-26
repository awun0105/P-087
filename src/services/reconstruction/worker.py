"""Worker entrypoint cho EX-REC: thực thi các pipeline stages và cập nhật lifecycle (REC-11)."""

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.artifacts import ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.manifests import (
    ExecutionError,
    JobStatus,
    StageArtifact,
    StageId,
    StageStatus,
)
from src.models.contracts.reconstruction import ReconstructionBundle
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.reconstruction.bundle import BundleBuildRequest, ReconstructionBundleService
from src.services.reconstruction.rgb.publication import ArtifactWriter

logger = logging.getLogger("ex_rec.worker")


class WorkerConfig(ContractModel):
    """Cấu hình khởi chạy reconstruction worker."""

    job_id: Identifier
    store_root: Path
    workspace_dir: Path
    bundle_request: BundleBuildRequest


class WorkerExecutionResult(ContractModel):
    """Kết quả bàn giao từ worker cho EX-PRODUCT orchestration."""

    job_id: Identifier
    status: JobStatus
    current_stage: StageId
    stage_artifacts: list[StageArtifact]
    bundle_ref: ProductArtifactRef | None = None
    error: ExecutionError | None = None


class ReconstructionWorker:
    """Worker độc lập điều phối việc tạo ReconstructionBundle với structured logging."""

    def __init__(self, config: WorkerConfig, writer: ArtifactWriter, resolver: ArtifactResolver) -> None:
        self.config = config
        self.writer = writer
        self.resolver = resolver
        self.bundle_service = ReconstructionBundleService(writer)

    def run(self) -> WorkerExecutionResult:
        """Thực thi pipeline bàn giao sang ReconstructionBundle, ghi nhận stage artifacts."""
        stage_artifacts: list[StageArtifact] = []
        started_at = datetime.now(UTC)
        try:
            bundle, ref = self._execute_metric_canonicalize(stage_artifacts, started_at)
            return WorkerExecutionResult(
                job_id=self.config.job_id,
                status=JobStatus.SUCCEEDED,
                current_stage=StageId.METRIC_CANONICALIZE,
                stage_artifacts=stage_artifacts,
                bundle_ref=ref,
            )
        except Exception as exc:
            err = self._handle_failure(exc, stage_artifacts, started_at)
            return WorkerExecutionResult(
                job_id=self.config.job_id,
                status=JobStatus.FAILED,
                current_stage=StageId.METRIC_CANONICALIZE,
                stage_artifacts=stage_artifacts,
                error=err,
            )

    def _execute_metric_canonicalize(
        self, stage_artifacts: list[StageArtifact], started_at: datetime
    ) -> tuple[ReconstructionBundle, ProductArtifactRef]:
        logger.info("Executing ST-METRIC-CANONICALIZE for job %s", self.config.job_id)
        bundle, ref = self.bundle_service.build_and_publish(self.config.bundle_request)
        stage_artifacts.append(
            StageArtifact(
                stage_id=StageId.METRIC_CANONICALIZE,
                status=StageStatus.SUCCEEDED,
                artifact_type="ReconstructionBundle",
                artifact_uri=ref.artifact_uri,
                artifact_checksum=ref.artifact_checksum,
                data_class=ref.data_class,
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
        )
        return bundle, ref

    def _handle_failure(
        self, exc: Exception, stage_artifacts: list[StageArtifact], started_at: datetime
    ) -> ExecutionError:
        logger.exception("Worker execution failed for job %s", self.config.job_id)
        err = ExecutionError(
            error_code="RECONSTRUCTION_FAILED",
            stage_id=StageId.METRIC_CANONICALIZE,
            human_message=str(exc),
            retryable=False,
        )
        stage_artifacts.append(
            StageArtifact(
                stage_id=StageId.METRIC_CANONICALIZE,
                status=StageStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=err,
            )
        )
        return err


def create_cli_parser() -> argparse.ArgumentParser:
    """Tạo argument parser cho worker CLI."""
    parser = argparse.ArgumentParser(description="EX-REC Reconstruction Worker")
    parser.add_argument("--job-id", type=str, required=True, help="Job identifier")
    parser.add_argument("--store-root", type=Path, required=True, help="Artifact store root path")
    parser.add_argument("--workspace", type=Path, required=True, help="Workspace directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entrypoint CLI của Reconstruction Worker trả về exit code cho orchestration."""
    parser = create_cli_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger.info("Worker CLI initialized for job %s", args.job_id)
    return 0
