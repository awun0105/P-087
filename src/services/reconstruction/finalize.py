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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ArtifactDataClass, Checksum, ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.coordinates import MetricScale
from src.models.contracts.manifests import (
    ExecutionError,
    InputConfiguration,
    StageArtifact,
    StageId,
    StageStatus,
)
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
from src.services.reconstruction.rgb.geometry.voxel import VoxelConfig
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter
from src.services.reconstruction.rgb.splat.visual_publication import VisualResolver

Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]


class GeometryProfile(ContractModel):
    """`configs/product/geometry_v1.json`: thông số REC-05 không kèm seed (seed tính theo scene)."""

    schema_version: Literal["1.0"] = "1.0"
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
    gpu_index: int = Field(ge=0, strict=True)


class FinalizeRequest(ContractModel):
    """Request bền vững của bước hoàn tất; không chứa đường dẫn runtime/secret."""

    schema_version: Literal["1.0"] = "1.0"
    execution_scope: Literal["product_finalize"] = "product_finalize"
    job_id: Identifier
    attempt_id: Identifier
    confirmation_ref: ProductArtifactRef
    authorized_decision_checksum: Checksum
    geometry: GeometryProfile


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
            result = result.model_copy(
                update={
                    "error": ExecutionError(
                        stage_id=StageId.RGB_GEOMETRY,
                        error_code="REC_FINALIZE_FAILED",
                        human_message=_human_message(error),
                        retryable=False,
                        details={"exception_type": type(error).__name__},
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
        cluster_seed = (seed[0], seed[1], profile.cluster_seed_height_m)
        config = VoxelConfig(
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
        )
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
        bundle = BundleBuildRequest(
            job_id=request.job_id,
            source_input_checksum=frames.input_manifest_checksum,
            input_configuration=InputConfiguration(rgb_present=True, registered_lidar_present=False),
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
            self.deps.writer, BundleDependencies(self.deps.resolve, verifier.verify_bundle)
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
