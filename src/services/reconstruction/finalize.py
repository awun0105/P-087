"""Hoàn tất pipeline EX-REC sau khi người dùng xác nhận tỉ lệ mét (REC-06 → REC-05 → REC-10).

Chuỗi, mỗi bước dùng service đã có và kiểm lại authority từ bytes:
1. REC-06 canonical: camera pose + Gaussian master/SOG sang hệ mét `world` (Z-up, sàn z=0).
2. REC-05 geometry: voxel/cluster/capsule carve bằng splat-transform → collision mesh GLB.
   Seed = camera đầu đã registered hạ xuống `capsule_height/2 + seed_floor_clearance_m`
   trên sàn người dùng xác nhận (owner chốt 2026-09-29, REC-05).
3. REC-06 final: đo lại đoạn kiểm C/D trên artifact canonical, ngưỡng theo công thức Q2.
4. REC-10: ReconstructionBundle bàn giao EX-SCENE/EX-SIM.

Authority: PRODUCT xác minh quyết định của người dùng rồi truyền checksum của nó
(`authorized_decision_checksum`); REC chỉ chấp nhận đúng quyết định đó. Review bundle
được suy từ quyết định ấy theo quy tắc Q1/Q2 (C/D bắt buộc, trong ngưỡng) và vẫn bị
BundleMetricVerifier đo lại, không tự tin số.
"""

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, FiniteFloat, SerializerFunctionWrapHandler, model_serializer, model_validator

from src.models.contracts.artifacts import ArtifactDataClass, Checksum, ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.coordinates import MetricScale
from src.models.contracts.manifests import (
    ExecutionError,
    InputConfiguration,
    StageArtifact,
    StageId,
    StageStatus,
)
from src.models.contracts.reconstruction import AlignmentRecord
from src.models.contracts.retryability import classify_retryability
from src.services.reconstruction.adapters.gaussian_scale import SplatTransformSimilarityAdapter
from src.services.reconstruction.adapters.splat import SplatArtifactProcessor
from src.services.reconstruction.adapters.voxel import SplatTransformVoxelAdapter
from src.services.reconstruction.adapters.voxel_runtime import VoxelProcess
from src.services.reconstruction.bundle import BundleBuildRequest, ReconstructionBundleService
from src.services.reconstruction.bundle_validation import BundleDependencies
from src.services.reconstruction.metric_port import MeasurementDeclaration, check_tolerance_m
from src.services.reconstruction.rgb.canonical.bundle_metric import BundleMetricDependencies, BundleMetricVerifier
from src.services.reconstruction.rgb.canonical.bundle_metric_models import BundleMetricAcceptance, BundleMetricRequest
from src.services.reconstruction.rgb.canonical.canonical_poses import CanonicalPoseService
from src.services.reconstruction.rgb.canonical.canonical_visual import (
    CanonicalVisualDependencies,
    CanonicalVisualService,
)
from src.services.reconstruction.rgb.canonical.canonical_visual_models import CanonicalVisualRequest
from src.services.reconstruction.rgb.canonical.metric import MetricCanonicalizer, MetricDependencies
from src.services.reconstruction.rgb.canonical.metric_models import DistanceAnchor, MetricAcceptance, MetricPreview
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.geometry.geometry_publication import (
    GeometryDependencies,
    GeometryExecutionRequest,
    GeometryPublisher,
    RgbGeometryService,
)
from src.services.reconstruction.rgb.geometry.voxel import (
    StatisticalOutlierRemovalConfig,
    VoxelConfig,
    require_voxel_capacity,
)
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter
from src.services.reconstruction.rgb.splat.visual_publication import VisualResolver

Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]


class GeometryProfile(ContractModel):
    """`configs/product/geometry_v1.json`: thông số REC-05 không kèm seed (seed tính theo scene)."""

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    profile: Identifier
    note: str = ""
    resolution_m: FiniteFloat = Field(gt=0)
    opacity: FiniteFloat = Field(gt=0, lt=1)
    cluster_resolution_m: FiniteFloat = Field(gt=0)
    cluster_opacity: FiniteFloat = Field(gt=0, lt=1)
    cluster_min_contribution: FiniteFloat = Field(ge=0)
    capsule_radius_m: FiniteFloat = Field(gt=0)
    capsule_height_m: FiniteFloat = Field(gt=0)
    max_seed_relocation_m: FiniteFloat = Field(gt=0)
    seed_floor_clearance_m: FiniteFloat = Field(ge=0)
    #: Vùng làm việc = khung bao camera nới `crop_margin_m` theo phương ngang, từ
    #: `-crop_below_floor_m` tới `crop_height_m` theo trục Z (sàn z=0).
    crop_margin_m: FiniteFloat = Field(gt=0)
    crop_below_floor_m: FiniteFloat = Field(ge=0)
    crop_height_m: FiniteFloat = Field(gt=0)
    #: Seed lọc cụm đặt ngay trên mặt sàn dưới camera đầu (sàn là cụm lớn liên thông).
    cluster_seed_height_m: FiniteFloat = Field(ge=0)
    cleanup: Literal["cluster", "floaters"]
    statistical_outlier_removal: StatisticalOutlierRemovalConfig | None = None
    gpu_index: int = Field(ge=0, strict=True)
    max_gaussian_scale_log: FiniteFloat | None = 1.0
    external_fill_size_m: FiniteFloat | None = Field(default=None, gt=0)

    @model_serializer(mode="wrap")
    def _versioned_payload(self, handler: SerializerFunctionWrapHandler) -> dict:
        """Keep legacy profile serialization unchanged for existing bundle checksums."""
        payload = handler(self)
        if self.schema_version != "1.2":
            payload.pop("external_fill_size_m", None)
        return payload

    @model_validator(mode="after")
    def _sor_requires_versioned_opt_in(self) -> "GeometryProfile":
        if self.statistical_outlier_removal is not None and self.schema_version not in ("1.1", "1.2"):
            raise ValueError("statistical outlier removal requires GeometryProfile schema 1.1 or 1.2")
        if self.external_fill_size_m is not None and self.schema_version != "1.2":
            raise ValueError("external fill requires GeometryProfile schema 1.2")
        return self


_MAX_VOXEL_CELLS = 1_500_000_000.0


def build_voxel_config(
    profile: GeometryProfile,
    crop: tuple[Vector3, Vector3],
    seed: Vector3,
) -> VoxelConfig:
    """Keep the requested cleanup profile intact; reject crops that require coarser voxels."""
    low, high = crop
    if profile.external_fill_size_m is not None:
        require_voxel_capacity(
            tuple(upper - lower for lower, upper in zip(low, high, strict=True)),
            profile.resolution_m,
            profile.external_fill_size_m,
        )
    volume_m3 = math.prod(upper - lower for lower, upper in zip(low, high, strict=True))
    minimum_resolution_m = (volume_m3 / _MAX_VOXEL_CELLS) ** (1 / 3) if volume_m3 > 0 else 0.0
    if minimum_resolution_m > profile.resolution_m:
        raise ValueError(
            f"requested voxel resolution {profile.resolution_m:g} m exceeds voxel capacity; "
            f"minimum feasible resolution is {minimum_resolution_m:g} m. "
            "Reduce the crop or explicitly select a coarser geometry profile."
        )

    cluster_seed = (seed[0], seed[1], profile.cluster_seed_height_m)
    return VoxelConfig(
        schema_version=profile.schema_version,
        resolution_m=profile.resolution_m,
        opacity=profile.opacity,
        cluster_resolution_m=profile.cluster_resolution_m,
        cluster_opacity=profile.cluster_opacity,
        cluster_min_contribution=profile.cluster_min_contribution,
        cluster_seed_world=cluster_seed,
        navigation_seed_world=seed,
        capsule_height_m=profile.capsule_height_m,
        capsule_radius_m=profile.capsule_radius_m,
        max_seed_relocation_m=profile.max_seed_relocation_m,
        gpu_index=profile.gpu_index,
        crop_box_world=crop,
        cleanup=profile.cleanup,
        statistical_outlier_removal=profile.statistical_outlier_removal,
        max_gaussian_scale_log=profile.max_gaussian_scale_log,
        external_fill_size_m=profile.external_fill_size_m,
    )


class FinalizeRequest(ContractModel):
    """Request bền vững của bước hoàn tất; không chứa đường dẫn runtime/secret."""

    schema_version: Literal["1.0"] = "1.0"
    execution_scope: Literal["product_finalize"] = "product_finalize"
    job_id: Identifier
    attempt_id: Identifier
    confirmation_ref: ProductArtifactRef
    authorized_decision_checksum: Checksum
    geometry: GeometryProfile
    #: `LidarPackageRecord` của job có gói LiDAR (ADR 0009); None = job chỉ có video.
    lidar_package_ref: ProductArtifactRef | None = None


class FinalizeResult(ContractModel):
    """Kết quả bàn giao cho PRODUCT: refs đã publish + stage artifacts hoặc lỗi."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["RecFinalizeResult"] = "RecFinalizeResult"
    job_id: Identifier
    attempt_id: Identifier
    confirmation_ref: ProductArtifactRef
    canonical_pose_ref: ProductArtifactRef | None = None
    canonical_visual_ref: ProductArtifactRef | None = None
    visual_delivery_ref: ProductArtifactRef | None = None
    geometry_ref: ProductArtifactRef | None = None
    geometry_manifest_ref: ProductArtifactRef | None = None
    verification_ref: ProductArtifactRef | None = None
    bundle_ref: ProductArtifactRef | None = None
    independent_error_m: FiniteFloat | None = None
    tolerance_m: FiniteFloat | None = None
    accepted_seed_world: Vector3 | None = None
    stage_artifacts: list[StageArtifact] = Field(default_factory=list)
    error: ExecutionError | None = None


class BundleReviewDecision(ContractModel):
    """Review bundle suy từ quyết định người dùng theo quy tắc Q1/Q2, không phải phê duyệt tay mới."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["BundleReviewDecision"] = "BundleReviewDecision"
    job_id: Identifier
    request_checksum: Checksum
    basis_decision_checksum: Checksum
    rule: Literal["owner_2026-09-29_Q1_Q2_independent_check"] = "owner_2026-09-29_Q1_Q2_independent_check"


@dataclass(frozen=True)
class FinalizeDependencies:
    """Runtime do CLI composition root inject; core không đọc env."""

    resolve: Callable[[ProductArtifactRef], Path]
    writer: ArtifactWriter
    voxel: VoxelProcess
    splat: SplatArtifactProcessor
    on_event: Callable[[StageArtifact], None] | None = None


def floor_seed(camera_center_world: Vector3, profile: GeometryProfile) -> Vector3:
    """Seed robot: chiếu camera xuống sàn z=0 rồi nâng nửa capsule + khe hở (REC-05 owner 2026-09-29)."""
    x, y, _ = camera_center_world
    return (x, y, profile.capsule_height_m / 2 + profile.seed_floor_clearance_m)


def _json_ref(job_id: str, attempt_id: str, name: str, payload: bytes, artifact_type: str) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/attempts/{attempt_id}/finalize/{name}",
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
    )


@dataclass(frozen=True)
class _LidarBinding:
    """Phần LiDAR của bundle: đám mây đã đăng ký, bản ghi căn chỉnh đã xác nhận và provenance đi kèm."""

    geometry_ref: ProductArtifactRef
    record: AlignmentRecord
    provenance: dict
    #: Đọc lại bản ghi căn chỉnh từ bytes đã publish và kiểm lại quyền xác nhận; cổng bundle bắt buộc có.
    load: Callable[[ProductArtifactRef], AlignmentRecord]


class FinalizeWorker:
    """Một attempt hoàn tất; trả FinalizeResult kể cả khi lỗi (process boundary)."""

    def __init__(self, dependencies: FinalizeDependencies) -> None:
        self.deps = dependencies
        frames = FrameSetResolver(dependencies.resolve, dependencies.resolve)
        self.visuals = VisualResolver(dependencies.resolve, CameraPoseResolver(dependencies.resolve, frames))

    def _event(self, stage_id: StageId, status: StageStatus, **fields: object) -> StageArtifact:
        now = datetime.now(UTC)
        stage = StageArtifact(
            stage_id=stage_id,
            status=status,
            started_at=now if status == StageStatus.RUNNING else None,
            completed_at=None if status == StageStatus.RUNNING else now,
            **fields,  # type: ignore[arg-type]
        )
        if self.deps.on_event is not None:
            self.deps.on_event(stage)
        return stage

    def run(self, request: FinalizeRequest, workspace: Path) -> tuple[FinalizeResult, ProductArtifactRef]:
        """Chạy đủ chuỗi; lỗi bất kỳ ghi thành ExecutionError, không để lọt publish dở."""
        request = FinalizeRequest.model_validate(request.model_dump())
        result = FinalizeResult(
            job_id=request.job_id, attempt_id=request.attempt_id, confirmation_ref=request.confirmation_ref
        )
        try:
            result = self._execute(request, workspace, result)
        except Exception as error:  # noqa: BLE001 - process boundary: ghi lỗi có cấu trúc, giữ type
            details = {"exception_type": type(error).__name__}
            result = result.model_copy(
                update={
                    "error": ExecutionError(
                        stage_id=StageId.RGB_GEOMETRY,
                        error_code="REC_FINALIZE_FAILED",
                        human_message=_human_message(error),
                        retryable=classify_retryability("REC_FINALIZE_FAILED", details),
                        details=details,
                    )
                }
            )
            self._event(StageId.RGB_GEOMETRY, StageStatus.FAILED, error=result.error)
        payload = result.model_dump_json(indent=2).encode() + b"\n"
        reference = _json_ref(request.job_id, request.attempt_id, "result.json", payload, result.artifact_type)
        if self.deps.writer.publish(reference, payload) != reference:
            raise ValueError("artifact writer changed finalize result identity")
        return result, reference

    def _canonicalizer(self, request: FinalizeRequest) -> MetricCanonicalizer:
        def verify(preview: MetricPreview, acceptance: MetricAcceptance) -> bool:
            """Chỉ đúng quyết định PRODUCT đã xác minh cho đúng preview này."""
            return (
                acceptance.decision_ref.artifact_checksum == request.authorized_decision_checksum
                and acceptance.decision_ref.job_id == request.job_id
                and acceptance.preview_checksum == preview.checksum()
            )

        return MetricCanonicalizer(MetricDependencies(self.visuals, self.deps.writer, verify))

    def _execute(self, request: FinalizeRequest, workspace: Path, result: FinalizeResult) -> FinalizeResult:
        canonicalizer = self._canonicalizer(request)
        confirmation = canonicalizer.require_real(request.confirmation_ref)
        self._event(StageId.RGB_GEOMETRY, StageStatus.RUNNING)

        poses_ref = CanonicalPoseService(canonicalizer).publish(request.confirmation_ref)
        poses = CanonicalPoseService(canonicalizer).load(poses_ref)
        similarity = SplatTransformSimilarityAdapter(self.deps.voxel)
        visual_service = CanonicalVisualService(CanonicalVisualDependencies(canonicalizer, similarity, self.deps.splat))
        visual_ref = visual_service.execute(
            CanonicalVisualRequest(confirmation_ref=request.confirmation_ref, canonical_pose_ref=poses_ref),
            workspace / "canonical",
        )
        manifest = visual_service.load(visual_ref)
        result = result.model_copy(
            update={
                "canonical_pose_ref": poses_ref,
                "canonical_visual_ref": visual_ref,
                "visual_delivery_ref": manifest.delivery_ref(),
            }
        )

        first = min(poses.poses, key=lambda pose: pose.frame_id)
        seed = floor_seed(first.translation, request.geometry)
        profile = request.geometry
        centers = [pose.translation for pose in poses.poses]
        crop = (
            (
                min(c[0] for c in centers) - profile.crop_margin_m,
                min(c[1] for c in centers) - profile.crop_margin_m,
                -profile.crop_below_floor_m,
            ),
            (
                max(c[0] for c in centers) + profile.crop_margin_m,
                max(c[1] for c in centers) + profile.crop_margin_m,
                profile.crop_height_m,
            ),
        )
        config = build_voxel_config(profile, crop, seed)
        raw_visual = confirmation.preview.request.source_visual
        geometry = RgbGeometryService(
            GeometryDependencies(
                canonicalizer,
                self.visuals,
                SplatTransformVoxelAdapter(self.deps.voxel),
                GeometryPublisher(self.deps.writer, request.job_id),
                # Chính sách seed: đúng seed suy từ camera theo quy tắc owner, không nhận seed lạ.
                verify_seed=lambda candidate: candidate.config.navigation_seed_world == seed,
            )
        ).execute(
            GeometryExecutionRequest(
                confirmation_ref=request.confirmation_ref,
                source_visual=raw_visual,
                config=config,
                job_id=request.job_id,
            ),
            workspace / "geometry",
        )
        accepted = tuple(geometry.report["accepted_navigation_seed"])
        result = result.model_copy(
            update={
                "geometry_ref": geometry.geometry_ref,
                "geometry_manifest_ref": geometry.manifest_ref,
                "accepted_seed_world": accepted,
            }
        )
        stages = [
            self._event(
                StageId.RGB_GEOMETRY,
                StageStatus.SUCCEEDED,
                artifact_type=geometry.geometry_ref.artifact_type,
                artifact_uri=geometry.geometry_ref.artifact_uri,
                artifact_checksum=geometry.geometry_ref.artifact_checksum,
                data_class=geometry.geometry_ref.data_class,
            )
        ]
        return self._bundle(request, canonicalizer, visual_service, result, stages)

    def _lidar_alignment(
        self, request: FinalizeRequest, result: FinalizeResult, distance_source: str
    ) -> "_LidarBinding | None":
        """Gắn đám mây LiDAR của gói vào bundle bằng `AlignmentRecord` CONFIRMED (ADR 0009).

        Chỉ khi người dùng đã xác nhận tỉ lệ từ chính căn chỉnh quỹ đạo: màn xác nhận khi đó cho họ xem độ lệch pose ↔
        quỹ đạo, nên lời xác nhận phủ cả việc LiDAR và scene cùng một chỗ. Job có gói LiDAR nhưng người dùng tự nhập
        số đo thì bundle vẫn chỉ có RGB — không tự coi căn chỉnh là đã được xác nhận.
        """
        if request.lidar_package_ref is None or distance_source != "lidar_trajectory":
            return None
        from src.models.contracts.reconstruction import AlignmentStatus
        from src.services.reconstruction.alignment.models import AlignmentRequest
        from src.services.reconstruction.alignment.service import RgbLidarAlignmentService
        from src.services.reconstruction.lidar.camera_priors import camera_priors
        from src.services.reconstruction.lidar.fusion import parse_trajectory
        from src.services.reconstruction.lidar.package import LidarPackageRecord
        from src.services.reconstruction.lidar.world_alignment import fit_world_from_lidar_map

        record = LidarPackageRecord.model_validate_json(self.visuals.require(request.lidar_package_ref).read_bytes())
        if record.job_id != request.job_id or result.canonical_pose_ref is None or result.geometry_ref is None:
            raise ValueError("gói LiDAR không thuộc job này hoặc scene chưa có pose/hình học canonical")
        canonical_pose_path = self.visuals.require(result.canonical_pose_ref)
        canonical_pose_payload = json.loads(canonical_pose_path.read_text())
        poses = sorted(canonical_pose_payload["poses"], key=lambda pose: pose["frame_id"])
        trajectory = parse_trajectory(self.visuals.require(record.trajectory_ref).read_text(encoding="utf-8"))
        source_frame_ids = None
        source_frame_count = None
        from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver

        source_frame_set = ProductArtifactRef.model_validate(canonical_pose_payload["source_frame_set"])
        frames = FrameSetResolver(self.deps.resolve, self.deps.resolve).load(source_frame_set)
        mapped = [frame.source_frame_id is not None for frame in frames.frames]
        if any(mapped) and not all(mapped):
            raise ValueError("canonical RGB frame set contains a partial source-frame map")
        if frames.video_preparation is not None:
            if not all(mapped):
                raise ValueError("canonical RGB frame set is missing its verified source-frame map")
            source_by_frame = {frame.frame_id: frame.source_frame_id for frame in frames.frames}
            source_frame_ids = tuple(source_by_frame[pose["frame_id"]] for pose in poses)
            source_frame_count = frames.video_preparation.client_manifest.source_video.frame_count
        priors = camera_priors(
            trajectory,
            record.sensor_from_camera,
            tuple(pose["frame_id"] for pose in poses),
            source_frame_ids,
            source_frame_count,
        )
        fit = fit_world_from_lidar_map(
            [prior.translation for prior in priors], [tuple(pose["translation"]) for pose in poses]
        )
        ground_truth = record.trajectory_origin == "ground_truth"
        evidence = {
            "schema_version": "1.0",
            "artifact_type": "LidarWorldAlignmentEvidence",
            "job_id": request.job_id,
            "method": fit.method,
            "frame_count": fit.pair_count,
            "inlier_frame_count": fit.inlier_pair_count,
            "rejected_frame_count": fit.rejected_pair_count,
            "inlier_threshold_m": fit.inlier_threshold_m,
            "base_inlier_threshold_m": fit.base_inlier_threshold_m,
            "max_outlier_fraction": fit.max_outlier_fraction,
            "ransac_iterations": fit.ransac_iterations,
            "random_seed": fit.random_seed,
            "rank_ratio": fit.rank_ratio,
            "prior_assumptions": list(fit.prior_assumptions),
            "residual_rms_m": fit.rms_residual_m,
            "residual_median_m": fit.median_residual_m,
            "residual_max_m": fit.max_residual_m,
            "lidar_package_checksum": request.lidar_package_ref.artifact_checksum,
            "canonical_pose_checksum": result.canonical_pose_ref.artifact_checksum,
            "trajectory_origin": record.trajectory_origin,
        }
        payload = json.dumps(evidence, sort_keys=True, indent=2).encode() + b"\n"
        evidence_ref = self.deps.writer.publish(
            _json_ref(request.job_id, request.attempt_id, "lidar-alignment.json", payload, evidence["artifact_type"]),
            payload,
        )
        alignment = AlignmentRequest(
            job_id=request.job_id,
            rgb_geometry_ref=result.geometry_ref,
            lidar_geometry_ref=record.lidar_geometry_ref,
            transform_target_from_source=fit.transform,
            method="trajectory_camera_centers",
            status=AlignmentStatus.CONFIRMED,
            evidence_refs=[evidence_ref, request.confirmation_ref],
            same_scene_attestation=True,
            provenance={"ground_truth_assisted": ground_truth, "confirmed_by": "metric_confirmation"},
        )

        def verify(candidate: AlignmentRequest) -> bool:
            # Chỉ chấp nhận đúng phép khớp vừa tính, gắn với đúng lời xác nhận tỉ lệ của người dùng.
            return (
                candidate.transform_target_from_source == fit.transform
                and candidate.evidence_refs == [evidence_ref, request.confirmation_ref]
                and candidate.lidar_geometry_ref == record.lidar_geometry_ref
            )

        service = RgbLidarAlignmentService(self.deps.writer, self.deps.resolve, verify)
        aligned, _ = service.align(alignment)
        return _LidarBinding(
            load=service.load,
            geometry_ref=record.lidar_geometry_ref,
            record=aligned,
            provenance={
                "ground_truth_assisted": ground_truth,
                "lidar_alignment": {
                    "method": fit.method,
                    "inlier_frame_count": fit.inlier_pair_count,
                    "rejected_frame_count": fit.rejected_pair_count,
                    "residual_median_m": round(fit.median_residual_m, 4),
                    "residual_max_m": round(fit.max_residual_m, 4),
                },
            },
        )

    def _bundle(
        self,
        request: FinalizeRequest,
        canonicalizer: MetricCanonicalizer,
        visual_service: CanonicalVisualService,
        result: FinalizeResult,
        stages: list[StageArtifact],
    ) -> FinalizeResult:
        confirmation = canonicalizer.require_real(request.confirmation_ref)
        anchor = confirmation.preview.request.anchor
        declaration = MeasurementDeclaration.model_validate_json(
            self.visuals.require(anchor.measurement_ref).read_bytes()
        )
        data = declaration.input
        tolerance = check_tolerance_m(data.distance_m, data.check_distance_m)
        raw = self.visuals.load(confirmation.preview.request.source_visual)
        frames = self.visuals.poses.frames.load(raw.source_frame_set)
        if not (result.visual_delivery_ref and result.canonical_pose_ref and result.geometry_ref):
            raise ValueError("bundle cần visual, pose và geometry canonical đã publish")
        lidar = self._lidar_alignment(request, result, data.distance_source)
        bundle = BundleBuildRequest(
            job_id=request.job_id,
            source_input_checksum=frames.input_manifest_checksum,
            input_configuration=InputConfiguration(
                rgb_present=True,
                registered_lidar_present=lidar is not None,
                declared_same_scene=True if lidar else None,
            ),
            lidar_geometry_ref=lidar.geometry_ref if lidar else None,
            alignment_record=lidar.record if lidar else None,
            metric_scale=MetricScale(status="CONFIRMED", meters_per_unit=1),
            rgb_frame_refs=[frame.image for frame in frames.frames],
            camera_pose_refs=[result.canonical_pose_ref],
            visual_artifact_ref=result.visual_delivery_ref,
            rgb_geometry_ref=result.geometry_ref,
            canonical_geometry_ref=result.geometry_ref,
            provenance={
                "evidence_kind": "real_measurement",
                "distance_source": data.distance_source,
                "geometry_profile": request.geometry.profile,
                "geometry_profile_checksum": "sha256:"
                + hashlib.sha256(request.geometry.model_dump_json().encode()).hexdigest(),
                **(lidar.provenance if lidar else {}),
            },
        )
        metric_request = BundleMetricRequest(
            bundle=bundle,
            confirmation_ref=request.confirmation_ref,
            canonical_visual_ref=result.canonical_visual_ref,  # type: ignore[arg-type]
            independent_sample=DistanceAnchor(
                anchor_id=f"user-cd-{anchor.measurement_ref.artifact_checksum.removeprefix('sha256:')[:12]}",
                source_master=anchor.source_master,
                point_a=data.check_a,
                point_b=data.check_b,
                distance_m=data.check_distance_m,
                measurement_ref=anchor.measurement_ref,
            ),
            tolerance_m=tolerance,
        )
        decision = BundleReviewDecision(
            job_id=request.job_id,
            request_checksum=metric_request.checksum(),
            basis_decision_checksum=request.authorized_decision_checksum,
        )
        decision_bytes = decision.model_dump_json(indent=2).encode() + b"\n"
        decision_ref = self.deps.writer.publish(
            _json_ref(request.job_id, request.attempt_id, "bundle-review.json", decision_bytes, decision.artifact_type),
            decision_bytes,
        )

        def verify_review(candidate: BundleMetricRequest, review: BundleMetricAcceptance) -> bool:
            stored = BundleReviewDecision.model_validate_json(self.visuals.require(review.decision_ref).read_bytes())
            return (
                stored.job_id == request.job_id
                and stored.request_checksum == candidate.checksum()
                and stored.basis_decision_checksum == request.authorized_decision_checksum
            )

        verifier = BundleMetricVerifier(BundleMetricDependencies(visual_service, verify_review))
        verification_ref = verifier.publish(
            metric_request,
            BundleMetricAcceptance(
                request_checksum=metric_request.checksum(), evidence_kind="real_measurement", decision_ref=decision_ref
            ),
        )
        record = verifier.load(verification_ref)
        _, bundle_ref = ReconstructionBundleService(
            self.deps.writer,
            BundleDependencies(self.deps.resolve, verifier.verify_bundle, lidar.load if lidar else None),
        ).build_and_publish(bundle.model_copy(update={"verification_ref": verification_ref}))
        stages.append(
            self._event(
                StageId.METRIC_CANONICALIZE,
                StageStatus.SUCCEEDED,
                artifact_type=bundle_ref.artifact_type,
                artifact_uri=bundle_ref.artifact_uri,
                artifact_checksum=bundle_ref.artifact_checksum,
                data_class=bundle_ref.data_class,
            )
        )
        return result.model_copy(
            update={
                "verification_ref": verification_ref,
                "bundle_ref": bundle_ref,
                "independent_error_m": record.independent_distance_error_m,
                "tolerance_m": tolerance,
                "stage_artifacts": stages,
            }
        )


def _human_message(error: Exception) -> str:
    """Thông báo cho người dùng; không kèm đường dẫn hay stderr của tool."""
    text = str(error)
    if "tolerance" in text or "independent" in text:
        return "Đoạn kiểm C–D đo lại trên scene đã quy đổi mét vượt ngưỡng; xác nhận lại tỉ lệ"
    if "seed" in text or "clearance" in text:
        return "Không tìm được chỗ trống cho robot quanh camera đầu; cần chọn điểm robot đứng"
    if "voxel capacity" in text:
        return "Vùng dựng vượt giới hạn voxel ở độ phân giải đã chọn; thu hẹp vùng làm việc hoặc xác nhận profile khác"
    return "Dựng hình học/collision hoặc đóng gói bundle thất bại; xem log attempt rồi thử lại"


def load_finalize_result(
    reference: ProductArtifactRef, resolve: Callable[[ProductArtifactRef], Path]
) -> FinalizeResult:
    """Consumer (PRODUCT) đọc lại kết quả và kiểm mọi ref đã publish tồn tại đúng checksum."""
    if reference.artifact_type != "RecFinalizeResult":
        raise ValueError("not a REC finalize result")
    result = FinalizeResult.model_validate_json(resolve(reference).read_bytes())
    if result.job_id != reference.job_id:
        raise ValueError("finalize result belongs to another job")
    for ref in (
        result.canonical_pose_ref,
        result.canonical_visual_ref,
        result.visual_delivery_ref,
        result.geometry_ref,
        result.geometry_manifest_ref,
        result.verification_ref,
        result.bundle_ref,
    ):
        if ref is not None:
            if ref.job_id != result.job_id:
                raise ValueError("finalize reference belongs to another job")
            resolve(ref)
    if result.error is None and result.bundle_ref is None:
        raise ValueError("finalize succeeded without a bundle")
    return result


def load_geometry_profile(path: Path) -> GeometryProfile:
    """Đọc file thông số REC-05 (không default ngầm)."""
    return GeometryProfile.model_validate(json.loads(path.read_text()))


class ConfirmationSummary(ContractModel):
    """Ref xác nhận REC-06 dựng lại từ bytes + quyết định người dùng mà nó mang theo."""

    reference: ProductArtifactRef
    preview_checksum: Checksum
    decision_ref: ProductArtifactRef


def confirmation_summary(
    artifact_uri: str, artifact_checksum: str, job_id: str, resolve: Callable[[ProductArtifactRef], Path]
) -> ConfirmationSummary:
    """PRODUCT chỉ lưu URI/checksum trong JobManifest; provenance của ref tính lại từ record.

    Không kiểm authority ở đây (việc của PRODUCT với decision_ref trả về, rồi REC kiểm lại
    khi chạy); chỉ bảo đảm bytes đúng checksum và đúng job.
    """
    from src.services.reconstruction.rgb.canonical.metric import _provenance
    from src.services.reconstruction.rgb.canonical.metric_models import MetricConfirmation

    probe = ProductArtifactRef(
        artifact_type="RGBMetricConfirmation",
        schema_version="1.0",
        artifact_uri=artifact_uri,
        artifact_checksum=artifact_checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
    )
    path = resolve(probe)
    if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != artifact_checksum:
        raise ValueError("metric confirmation bytes differ from job manifest checksum")
    record = MetricConfirmation.model_validate_json(path.read_bytes())
    reference = probe.model_copy(update={"source_provenance": _provenance(record)})
    return ConfirmationSummary(
        reference=reference,
        preview_checksum=record.acceptance.preview_checksum,
        decision_ref=record.acceptance.decision_ref,
    )
