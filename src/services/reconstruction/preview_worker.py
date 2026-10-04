"""Worker REC-03→04: compose core adapters, publish attempt events và preview checkpoint."""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import ExecutionError, StageArtifact, StageId, StageStatus
from src.models.contracts.preview import ReconstructionPreview
from src.services.reconstruction.adapters.brush import BrushAdapter, BrushDependencies, BrushRequest
from src.services.reconstruction.adapters.brush_input import BrushInputAdapter
from src.services.reconstruction.adapters.brush_runtime import VisualError, VisualProcess
from src.services.reconstruction.adapters.colmap import ColmapAdapter, ColmapDependencies, ColmapRequest
from src.services.reconstruction.adapters.colmap_priors import PoseGuidance, PosePrior
from src.services.reconstruction.adapters.colmap_runtime import ColmapError, ColmapProcess
from src.services.reconstruction.adapters.splat import SplatArtifactProcessor
from src.services.reconstruction.attempt import PublicationNamespace
from src.services.reconstruction.lidar.camera_priors import CameraPriorError, camera_priors
from src.services.reconstruction.lidar.fusion import parse_trajectory
from src.services.reconstruction.lidar.package import LidarPackageRecord
from src.services.reconstruction.preview_models import PreparedPreviewRequest, PreparedPreviewResult
from src.services.reconstruction.resume import ResumeCache
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver, _sha256
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter
from src.services.reconstruction.rgb.splat.visual_publication import VisualPublisher, VisualResolver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreviewDependencies:
    """Composition root inject runtime/store; worker không biết API/queue implementation."""

    frames: FrameSetResolver
    writer: ArtifactWriter
    resolve: Callable[[ProductArtifactRef], Path]
    colmap: ColmapProcess
    brush: VisualProcess
    splat: SplatArtifactProcessor
    #: Báo stage event cho orchestrator (sau khi event đã publish); None = không báo.
    on_event: Callable[[StageArtifact], None] | None = None
    #: Kho dùng lại COLMAP + checkpoint Brush giữa các attempt trên cùng máy; None = luôn chạy từ đầu.
    resume: ResumeCache | None = None


class PreparedPreviewWorker:
    """Một instance cho một attempt; product orchestration vẫn sở hữu job lifecycle."""

    def __init__(self, dependencies: PreviewDependencies) -> None:
        self.deps = dependencies

    def run(self, request: PreparedPreviewRequest, workspace: Path) -> tuple[PreparedPreviewResult, ProductArtifactRef]:
        """Claim create-only trước chạy tools; retry cần attempt ID và workspace mới."""
        request = PreparedPreviewRequest.model_validate(request.model_dump())
        workspace.mkdir(parents=True, exist_ok=False)
        publication = _AttemptPublication(request, self.deps)
        request_ref = publication.publish(("PreviewRequest", "request.json"), request.model_dump_json().encode())
        execution = _PreviewExecution(request, self.deps, publication)
        result = execution.run(workspace, request_ref)
        reference = publication.publish(("PreparedPreviewResult", "result.json"), result.model_dump_json().encode())
        self.load(reference)
        return result, reference

    def load(self, reference: ProductArtifactRef) -> PreparedPreviewResult:
        """Consumer recheck checkpoint và payloads, không cần private workspace hoặc chạy tools."""
        from src.services.reconstruction.preview_validation import PreviewReadDependencies, load_preview

        return load_preview(reference, PreviewReadDependencies(self.deps.frames, self.deps.resolve))


class _AttemptPublication:
    def __init__(self, request: PreparedPreviewRequest, deps: PreviewDependencies) -> None:
        self.namespace = PublicationNamespace(job_id=request.job_id, attempt_id=request.attempt_id)
        self.deps = deps
        self.current_stage = StageId.FRAME_EXTRACT
        self.event_index = 0

    def publish(self, spec: tuple[str, str], payload: bytes) -> ProductArtifactRef:
        reference = ProductArtifactRef(
            schema_version="1.0",
            artifact_type=spec[0],
            data_class="derived",
            artifact_uri=self.namespace.uri("rec11", spec[1]),
            artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            job_id=self.namespace.job_id,
            producer_stage=self.current_stage,
            source_provenance={"execution_scope": "prepared_rgb_preview", **self.namespace.provenance()},
        )
        if self.deps.writer.publish(reference, payload) != reference:
            raise ValueError("attempt publication identity changed")
        if _sha256(self.deps.resolve(reference)) != reference.artifact_checksum:
            raise ValueError("attempt publication checksum mismatch")
        return reference

    def event(self, stage: StageArtifact) -> None:
        self.current_stage = stage.stage_id
        self.publish(("StageArtifact", f"events/{self.event_index:04d}.json"), stage.model_dump_json().encode())
        self.event_index += 1
        if self.deps.on_event is not None:
            self.deps.on_event(stage)


class _PreviewExecution:
    def __init__(
        self, request: PreparedPreviewRequest, deps: PreviewDependencies, publication: _AttemptPublication
    ) -> None:
        self.request, self.deps, self.publication = request, deps, publication
        self.stages: list[StageArtifact] = []
        self.poses = CameraPoseResolver(deps.resolve, deps.frames)
        self.visuals = VisualResolver(deps.resolve, self.poses)
        self.pose_ref: ProductArtifactRef | None = None
        self.guidance_ref: ProductArtifactRef | None = None
        self.resume_key: str | None = None
        self.visual_ref: ProductArtifactRef | None = None
        self.delivery_ref: ProductArtifactRef | None = None
        self.preview_ref: ProductArtifactRef | None = None

    def run(self, workspace: Path, request_ref: ProductArtifactRef) -> PreparedPreviewResult:
        error = None
        try:
            self._validate_source()
            self._colmap(workspace / "colmap")
            self._brush(workspace / "brush")
        except Exception as cause:
            # Process boundary: lưu failure stage, không serialize tool stderr/private paths.
            logger.error("Preview failed job=%s cause=%s", self.request.job_id, type(cause).__name__)
            error = self._failure(cause)
        return PreparedPreviewResult(
            job_id=self.request.job_id,
            attempt_id=self.request.attempt_id,
            source_input_checksum=self.request.source_input_checksum,
            request_ref=request_ref,
            preview_complete=error is None,
            job_status="RUNNING" if error is None else "FAILED",
            stage_artifacts=self.stages,
            camera_pose_ref=self.pose_ref,
            raw_visual_ref=self.visual_ref,
            delivery_ref=self.delivery_ref,
            preview_ref=self.preview_ref,
            pose_guidance_ref=self.guidance_ref,
            error=error,
        )

    def _guidance(self) -> PoseGuidance | None:
        """Pose camera từ gói LiDAR của job (nếu có): dòng quỹ đạo thứ `frame_id` ghép với calibration."""
        reference = self.request.lidar_package_ref
        if reference is None:
            return None
        record = LidarPackageRecord.model_validate_json(self.deps.resolve(reference).read_bytes())
        if record.job_id != self.request.job_id:
            raise ValueError("LiDAR package record belongs to another job")
        poses = parse_trajectory(self.deps.resolve(record.trajectory_ref).read_text(encoding="utf-8"))
        frames = self.deps.frames.load(self.request.frame_set_ref)
        frame_ids = tuple(frame.frame_id for frame in frames.frames)
        priors = camera_priors(poses, record.sensor_from_camera, frame_ids)
        camera = record.camera
        return PoseGuidance(
            tuple(PosePrior(f"{prior.frame_id:06d}.png", prior.translation, prior.rotation_xyzw) for prior in priors),
            None
            if camera is None
            else (camera.width, camera.height, (camera.fx, camera.fy, camera.cx, camera.cy, *camera.distortion)),
        )

    def _validate_source(self) -> None:
        frames = self.deps.frames.load(self.request.frame_set_ref)
        if frames.input_manifest_checksum != self.request.source_input_checksum:
            raise ValueError("prepared frames differ from source InputManifest identity")
        self.deps.frames.materialize(frames)

    def _start(self, stage: StageId) -> None:
        self.publication.event(StageArtifact(stage_id=stage, status=StageStatus.RUNNING, started_at=datetime.now(UTC)))

    def _complete(self, stage: StageArtifact) -> None:
        self.publication.event(stage)
        self.stages.append(stage)

    def _colmap(self, workspace: Path) -> None:
        self._start(StageId.CAMERA_POSE)
        deps = ColmapDependencies(
            self.deps.frames, self.deps.colmap, self.deps.writer, self.deps.resolve, self.deps.resume
        )
        result = ColmapAdapter(deps).execute(
            ColmapRequest(
                frame_set=self.request.frame_set_ref,
                config=self.request.colmap,
                workspace=workspace,
                job_id=self.request.job_id,
                attempt_id=self.request.attempt_id,
                guidance=self._guidance(),
            )
        )
        self._complete(result.stage)
        self.pose_ref, self.resume_key, self.guidance_ref = result.reference, result.resume_key, result.guidance_ref

    def _brush(self, workspace: Path) -> None:
        self._start(StageId.VISUAL_RECON)
        if self.pose_ref is None:
            raise ValueError("COLMAP did not publish camera poses")
        deps = BrushDependencies(
            BrushInputAdapter(self.poses, self.deps.colmap),
            self.deps.brush,
            self.deps.splat,
            VisualPublisher(self.deps.writer, self.request.job_id, self.request.attempt_id),
            self.visuals,
            self.deps.resume,
        )
        result = BrushAdapter(deps).execute(BrushRequest(self.pose_ref, self.request.brush, workspace, self.resume_key))
        self._complete(result.stage)
        self.visual_ref, self.delivery_ref = result.reference, result.artifact.delivery
        preview = ReconstructionPreview(
            job_id=self.request.job_id,
            attempt_id=self.request.attempt_id,
            source_input_checksum=self.request.source_input_checksum,
            source_visual_ref=result.reference,
            camera_pose_ref=self.pose_ref,
            delivery_ref=result.artifact.delivery,
            producer_version=result.artifact.brush_version,
        )
        self.preview_ref = self.publication.publish(
            ("ReconstructionPreview", "preview.json"), preview.model_dump_json().encode()
        )

    def _failure(self, cause: Exception) -> ExecutionError:
        # Lỗi do gói LiDAR không khớp video là lỗi người dùng sửa được: giữ nguyên lý do, không dùng câu chung.
        lidar = isinstance(cause, CameraPriorError) or (
            isinstance(cause, ColmapError) and cause.code == "COLMAP_GUIDANCE_INVALID"
        )
        visual = isinstance(cause, VisualError)
        error_code = "LIDAR_ALIGNMENT_INVALID" if lidar else cause.code if visual else "RECONSTRUCTION_PREVIEW_FAILED"
        human_message = (
            str(cause)
            if lidar or visual
            else "Preview failed; inspect attempt logs and configured runtime before retrying"
        )
        error = ExecutionError(
            error_code=error_code,
            stage_id=self.publication.current_stage,
            human_message=human_message,
            retryable=True,
            details={"exception_type": type(cause).__name__},
        )
        self._complete(
            StageArtifact(
                stage_id=error.stage_id,
                status=StageStatus.FAILED,
                completed_at=datetime.now(UTC),
                error=error,
            )
        )
        return error
