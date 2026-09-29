"""REC-11 verified-bundle publication worker; chưa là full reconstruction dispatch."""

import argparse
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator

from src.models.contracts.artifacts import ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.manifests import (
    ExecutionError,
    JobStatus,
    StageArtifact,
    StageId,
    StageStatus,
)
from src.models.contracts.reconstruction import ReconstructionBundle
from src.services.reconstruction.bundle import BundleBuildRequest, ReconstructionBundleService
from src.services.reconstruction.bundle_validation import BundleDependencies
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter

logger = logging.getLogger("ex_rec.worker")


class WorkerConfig(ContractModel):
    """Cấu hình khởi chạy reconstruction worker."""

    schema_version: Literal["1.0"] = "1.0"
    execution_scope: Literal["verified_bundle_publication"] = "verified_bundle_publication"
    job_id: Identifier
    store_root: Path
    workspace_dir: Path
    bundle_request: BundleBuildRequest

    @model_validator(mode="after")
    def _bind_job(self) -> Self:
        if self.job_id != self.bundle_request.job_id:
            raise ValueError("worker and bundle job_id must match")
        return self


class WorkerExecutionResult(ContractModel):
    """Kết quả bàn giao từ worker cho EX-PRODUCT orchestration."""

    execution_scope: Literal["verified_bundle_publication"] = "verified_bundle_publication"
    job_id: Identifier
    status: JobStatus
    current_stage: StageId
    stage_artifacts: list[StageArtifact]
    bundle_ref: ProductArtifactRef | None = None
    error: ExecutionError | None = None


class ReconstructionWorker:
    """Worker độc lập điều phối việc tạo ReconstructionBundle với structured logging."""

    def __init__(self, config: WorkerConfig, writer: ArtifactWriter, dependencies: BundleDependencies) -> None:
        self.config = WorkerConfig.model_validate(config.model_dump())
        self.writer = writer
        self.dependencies = dependencies
        self.bundle_service = ReconstructionBundleService(writer, dependencies)

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
            # Process boundary: structured failure, không để tool/private paths lọt log.
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
        logger.info("Publishing verified bundle for job %s", self.config.job_id)
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
        logger.error("Bundle publication failed job=%s cause=%s", self.config.job_id, type(exc).__name__)
        err = ExecutionError(
            error_code="RECONSTRUCTION_FAILED",
            stage_id=StageId.METRIC_CANONICALIZE,
            human_message="Bundle publication failed; check input identities, payloads and metric/alignment evidence",
            retryable=False,
            details={"exception_type": type(exc).__name__, "execution_scope": self.config.execution_scope},
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
    parser.add_argument("--request", type=Path, required=True, help="Path to versioned config or bundle request JSON")
    parser.add_argument("--output", type=Path, default=None, help="Path to write execution result JSON")
    return parser


def _load_worker_config(args: argparse.Namespace) -> WorkerConfig:
    """Đọc cấu hình WorkerConfig từ file JSON yêu cầu."""
    payload = json.loads(args.request.read_text())
    if not isinstance(payload, dict):
        raise ValueError("worker request must be a JSON object")
    if "bundle_request" in payload:
        config = WorkerConfig.model_validate(payload)
    else:
        config = WorkerConfig(
            job_id=args.job_id,
            store_root=args.store_root,
            workspace_dir=args.workspace,
            bundle_request=BundleBuildRequest.model_validate(payload),
        )
    if config.job_id != args.job_id or config.store_root.resolve() != args.store_root.resolve():
        raise ValueError("CLI job/store differs from worker config")
    if config.workspace_dir.resolve() != args.workspace.resolve():
        raise ValueError("CLI workspace differs from worker config")
    return config


def _run_worker_cli(args: argparse.Namespace) -> int:
    """Khởi chạy worker với FilesystemArtifactStore và ghi kết quả."""
    # CLI composition root chỉ dùng public storage facade; core worker nhận ports.
    from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore

    config = _load_worker_config(args)
    logger.info("Worker CLI initialized for job %s", config.job_id)
    if args.output is not None and args.output.exists():
        raise ValueError("execution output already exists; use a new attempt path")
    resolver = ArtifactResolver(args.store_root)
    store = FilesystemArtifactStore(resolver)
    # Chưa có qualified REC-06 derivative verifier để wire CLI; fail closed.
    worker = ReconstructionWorker(config, store, BundleDependencies(resolver.require))
    result = worker.run()
    if args.output is not None:
        _write_execution_result(args.output, result)
    print(result.model_dump_json())
    return 0 if result.status == JobStatus.SUCCEEDED else 1


def _write_execution_result(path: Path, result: WorkerExecutionResult) -> None:
    """Atomic create-only result; retry ghi path mới, không rewrite attempt cũ."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rec11-", dir=path.parent) as directory:
        temporary = Path(directory) / "result.json"
        temporary.write_text(result.model_dump_json(indent=2) + "\n")
        os.link(temporary, path)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint CLI của Reconstruction Worker trả về exit code cho orchestration."""
    parser = create_cli_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    try:
        return _run_worker_cli(args)
    except (ValueError, OSError, RuntimeError) as error:
        logger.error("Worker CLI setup failed cause=%s", type(error).__name__)
        print(
            json.dumps({"status": "FAILED", "error_code": "INVALID_WORKER_SETUP", "error_type": type(error).__name__})
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
