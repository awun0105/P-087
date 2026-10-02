"""Public port REC-06 cho PRODUCT: xác nhận tỉ lệ mét từ điểm người dùng chọn trên scene.

PRODUCT chỉ đưa vào: preview contract của job, điểm chọn (hệ gốc 3DGS = SfM) và khoảng
cách; nhận lại preview checksum + số liệu kiểm tra. Authority (ai xác nhận) do PRODUCT
cấp qua `verify` và `decision_ref`; REC không tự xác nhận thay người dùng.

Owner chốt 2026-09-29 (REC-06):
- C/D là đoạn kiểm độc lập bắt buộc; tỉ lệ từ A/B phải đo lại C/D trong ngưỡng
  `2·√2·e·(1 + L_CD/L_AB)`, mỗi đoạn ≥ 0,5 m, ngưỡng ≤ 5% L_CD;
- dataset mẫu lấy khoảng cách từ LiDAR (`distance_source="lidar_demo"`, ADR 0004 §6):
  server tự đo lại, không tin số client gửi.
"""

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import canonical_json_bytes
from src.models.contracts.manifests import StageId
from src.services.reconstruction.metric_proposal import MetricProposal, load_proposal, proposal_uri
from src.services.reconstruction.rgb.canonical.floor_frame import floor_frame
from src.services.reconstruction.rgb.canonical.lidar_assist import (
    LidarAssist,
    LidarAssistContext,
    LidarDistance,
    demo_points,
)
from src.services.reconstruction.rgb.canonical.metric import MetricCanonicalizer, MetricDependencies
from src.services.reconstruction.rgb.canonical.metric_math import scale_from_distance
from src.services.reconstruction.rgb.canonical.metric_models import (
    CanonicalFrameDeclaration,
    DistanceAnchor,
    MetricAcceptance,
    MetricConfirmation,
    MetricPreview,
    MetricRequest,
)
from src.services.reconstruction.rgb.canonical.mode_comparison import ModeComparison, compare_modes
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.pose.pose_publication import CameraPoseResolver
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter
from src.services.reconstruction.rgb.splat.visual_publication import VisualResolver

Point = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
#: `ai_estimated`: khoảng cách lấy từ đề xuất tự động (ADR 0001 §2) — người dùng chấp nhận ước lượng,
#: không phải số đo ngoài đời; bản khai giữ lại đề xuất đã dùng.
DistanceSource = Literal["user_measured", "lidar_demo", "ai_estimated"]

#: Sai số click một điểm trên 3DGS — PROPOSAL tạm, đo và khóa ở gói 2 (REC-06).
CLICK_UNCERTAINTY_M = 0.01
MIN_SEGMENT_M = 0.5
MAX_TOLERANCE_RATIO = 0.05
#: Số LiDAR client gửi lại phải trùng số server đo (chỉ chênh do làm tròn JSON).
_LIDAR_MATCH_M = 1e-6
#: Khoảng cách nguồn `ai_estimated` phải trùng độ dài SfM × tỉ lệ đề xuất (chỉ chênh do làm tròn).
_ESTIMATE_MATCH_M = 1e-6


def check_tolerance_m(distance_ab_m: float, distance_cd_m: float) -> float:
    """Ngưỡng sai lệch cho phép của đoạn kiểm C/D (hệ số 2 ≈ 95%)."""
    return 2 * math.sqrt(2) * CLICK_UNCERTAINTY_M * (1 + distance_cd_m / distance_ab_m)


class UserMetricInput(BaseModel):
    """A/B (đoạn tính tỉ lệ), C/D (đoạn kiểm), 3 điểm sàn — hệ gốc file 3DGS — và số đo (mét)."""

    model_config = ConfigDict(extra="forbid")

    floor_points: tuple[Point, Point, Point]
    point_a: Point
    point_b: Point
    distance_m: FiniteFloat = Field(gt=0, le=1000)
    check_a: Point
    check_b: Point
    check_distance_m: FiniteFloat = Field(gt=0, le=1000)
    distance_source: DistanceSource = "user_measured"


class LidarEvidence(BaseModel):
    """Số đo LiDAR đã dùng (dataset mẫu), gắn với bản ghi hỗ trợ của job."""

    model_config = ConfigDict(extra="forbid")

    support_checksum: str
    anchor: LidarDistance
    check: LidarDistance


class EstimateEvidence(BaseModel):
    """Đề xuất tự động mà người dùng đã chấp nhận làm khoảng cách (không phải số đo ngoài đời)."""

    model_config = ConfigDict(extra="forbid")

    proposal_checksum: str
    method: str
    scale_m_per_sfm_unit: float
    relative_uncertainty: float
    frames_used: int


class MeasurementDeclaration(BaseModel):
    """Bản khai đo đạc: measurement_ref + frame evidence_ref của REC-06."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    artifact_type: Literal["MetricMeasurementDeclaration"] = "MetricMeasurementDeclaration"
    job_id: str
    method: Literal["user_floor_plane_and_anchor"] = "user_floor_plane_and_anchor"
    source_visual_checksum: str
    input: UserMetricInput
    lidar: LidarEvidence | None = None
    estimate: EstimateEvidence | None = None


class UserMetricPreview(BaseModel):
    """Số liệu để người dùng tự kiểm trước khi xác nhận (không phải xác nhận)."""

    model_config = ConfigDict(extra="forbid")

    preview_checksum: str
    scale_m_per_sfm_unit: float
    floor_residual_m: float
    measured_distance_m: float
    camera_height_min_m: float
    camera_height_max_m: float
    distance_source: DistanceSource
    check_measured_m: float
    check_error_m: float
    check_tolerance_m: float
    check_passed: bool


class LidarMeasurements(BaseModel):
    """Số đo LiDAR cho A/B và C/D để UI điền sẵn (dataset mẫu)."""

    model_config = ConfigDict(extra="forbid")

    anchor: LidarDistance
    check: LidarDistance


class DemoSelection(BaseModel):
    """7 điểm tự chọn từ LiDAR (A, B, C, D, 3 điểm sàn — hệ SfM) + số đo của chúng."""

    model_config = ConfigDict(extra="forbid")

    points: list[Point]
    measurements: LidarMeasurements


@dataclass(frozen=True)
class _Built:
    preview: MetricPreview
    summary: UserMetricPreview


def publish_json(
    writer: ArtifactWriter, exists: Callable[[str], bool], job_id: str, kind: str, model: BaseModel, artifact_type: str
) -> ProductArtifactRef:
    """Publish JSON bất biến theo nội dung dưới `rec06/<kind>/` (cùng nội dung → cùng ref)."""
    payload = canonical_json_bytes(model)
    digest = hashlib.sha256(payload).hexdigest()
    reference = ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec06/{kind}/{digest}.json",
        artifact_checksum=f"sha256:{digest}",
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
    )
    if not exists(reference.artifact_uri):
        writer.publish(reference, payload)
    return reference


class UserMetricPort:
    """Xem trước / xác nhận REC-06 cho một job; resolver + writer do PRODUCT inject."""

    def __init__(
        self,
        resolve: Callable[[ProductArtifactRef], Path],
        writer: ArtifactWriter,
        exists: Callable[[str], bool],
        locate: Callable[[str], Path | None] | None = None,
    ) -> None:
        #: Tìm file theo URI cố định (đề xuất tự động); None = deployment không có đề xuất.
        self.locate = locate
        frames = FrameSetResolver(resolve, resolve)
        self.poses = CameraPoseResolver(resolve, frames)
        self.visuals = VisualResolver(resolve, self.poses)
        self.writer = writer
        self.exists = exists
        self.lidar = LidarAssist(resolve, exists)

    def _lidar_context(
        self, job_id: str, source_visual: ProductArtifactRef, support: ProductArtifactRef | None
    ) -> LidarAssistContext:
        context = self.lidar.load(job_id, support)
        if context is None:
            raise ValueError("Scene này không có số đo LiDAR; nhập khoảng cách đo ngoài đời")
        poses = self.visuals.load(source_visual).source_camera_poses
        if context.support.camera_poses_checksum != poses.artifact_checksum:
            raise ValueError("Căn chỉnh LiDAR dựng cho camera pose khác của scene")
        return context

    def lidar_measurements(
        self,
        job_id: str,
        source_visual: ProductArtifactRef,
        support: ProductArtifactRef | None,
        anchor: tuple[Point, Point],
        check: tuple[Point, Point],
    ) -> LidarMeasurements:
        """Đo A/B và C/D trên LiDAR (dataset mẫu) để UI điền sẵn số đo."""
        context = self._lidar_context(job_id, source_visual, support)
        return LidarMeasurements(anchor=self.lidar.measure(context, *anchor), check=self.lidar.measure(context, *check))

    def demo_selection(
        self, job_id: str, source_visual: ProductArtifactRef, support: ProductArtifactRef | None
    ) -> DemoSelection:
        """Dataset mẫu: tự chọn 7 điểm trên sàn LiDAR để demo luồng xác nhận (ADR 0004 §6)."""
        context = self._lidar_context(job_id, source_visual, support)
        visual = self.visuals.load(source_visual)
        cameras = [pose.translation for pose in self.poses.load(visual.source_camera_poses).poses]
        points = demo_points(context, cameras)
        measured = LidarMeasurements(
            anchor=self.lidar.measure(context, points[0], points[1]),
            check=self.lidar.measure(context, points[2], points[3]),
        )
        return DemoSelection(points=points, measurements=measured)

    def mode_comparison(
        self,
        job_id: str,
        source_visual: ProductArtifactRef,
        confirmation: ProductArtifactRef | None,
        support: ProductArtifactRef | None,
    ) -> ModeComparison:
        """So sánh RGB only (mock) / anchor người dùng / LiDAR trên cùng camera (chỉ hiển thị).

        Bản xác nhận được đọc từ bytes đã kiểm checksum để hiển thị; authority đã được kiểm
        khi xác nhận và sẽ kiểm lại ở mọi bước dùng nó để sinh artifact.
        """
        visual = self.visuals.load(source_visual)
        cameras = [pose.translation for pose in self.poses.load(visual.source_camera_poses).poses]
        user = None
        check = None
        if confirmation is not None:
            record = MetricConfirmation.model_validate_json(self.visuals.require(confirmation).read_bytes())
            user = record.preview.transform
            declaration = MeasurementDeclaration.model_validate_json(
                self.visuals.require(record.preview.request.anchor.measurement_ref).read_bytes()
            )
            check = (declaration.input.check_a, declaration.input.check_b)
        lidar = self._lidar_context(job_id, source_visual, support).fit if support is not None else None
        result = compare_modes(job_id, cameras, user, lidar, check)
        if confirmation is not None and declaration.input.distance_source == "lidar_demo":
            # Điểm/số đo tự chọn từ LiDAR: độ lệch với cột LiDAR gần 0 là đương nhiên, không phải
            # độ chính xác của người click. Click tay mới lộ sai số thật.
            modes = [
                mode.model_copy(update={"note": mode.note + " Số đo A–B, C–D lấy từ LiDAR (dataset mẫu)."})
                if mode.mode == "user_anchor"
                else mode
                for mode in result.modes
            ]
            result = result.model_copy(update={"modes": modes})
        return result

    def _evidence(
        self, job_id: str, source_visual: ProductArtifactRef, data: UserMetricInput, support: ProductArtifactRef | None
    ) -> LidarEvidence | None:
        if data.distance_source != "lidar_demo":
            return None
        measured = self.lidar_measurements(
            job_id, source_visual, support, (data.point_a, data.point_b), (data.check_a, data.check_b)
        )
        if (
            abs(measured.anchor.distance_m - data.distance_m) > _LIDAR_MATCH_M
            or abs(measured.check.distance_m - data.check_distance_m) > _LIDAR_MATCH_M
        ):
            raise ValueError("Số đo LiDAR không khớp điểm đã chọn; lấy lại số đo từ LiDAR")
        if support is None:  # _lidar_context đã từ chối; giữ kiểm tra cho type checker
            raise ValueError("Scene này không có số đo LiDAR")
        return LidarEvidence(support_checksum=support.artifact_checksum, anchor=measured.anchor, check=measured.check)

    def auto_proposal(self, job_id: str, source_visual: ProductArtifactRef) -> MetricProposal | None:
        """Đề xuất tỉ lệ/mặt sàn tự động của đúng bản 3DGS này; None khi worker không tạo."""
        if self.locate is None:
            return None
        return load_proposal(job_id, source_visual, self.locate)

    def _estimate(
        self, job_id: str, source_visual: ProductArtifactRef, data: UserMetricInput
    ) -> EstimateEvidence | None:
        """Nguồn `ai_estimated` chỉ hợp lệ khi hai khoảng cách đúng bằng độ dài SfM × tỉ lệ của đề xuất.

        Người dùng được chọn điểm khác với điểm đề xuất (vd. tự chọn sàn), nhưng không được khai một
        con số tự nghĩ ra dưới nhãn ước lượng tự động: số đo thật phải gửi với nguồn `user_measured`.
        """
        if data.distance_source != "ai_estimated":
            return None
        proposal = self.auto_proposal(job_id, source_visual)
        if proposal is None or self.locate is None:
            raise ValueError("Scene này không có đề xuất tỉ lệ tự động; nhập khoảng cách đo ngoài đời")
        scale = proposal.scale_m_per_sfm_unit
        expected = (math.dist(data.point_a, data.point_b) * scale, math.dist(data.check_a, data.check_b) * scale)
        if (
            abs(expected[0] - data.distance_m) > _ESTIMATE_MATCH_M
            or abs(expected[1] - data.check_distance_m) > _ESTIMATE_MATCH_M
        ):
            raise ValueError("Khoảng cách không khớp đề xuất tự động; lấy lại đề xuất hoặc nhập số đo thật")
        path = self.locate(proposal_uri(job_id, source_visual))
        if path is None:  # auto_proposal vừa đọc được; giữ kiểm tra cho type checker
            raise ValueError("Scene này không có đề xuất tỉ lệ tự động")
        with path.open("rb") as stream:
            checksum = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
        return EstimateEvidence(
            proposal_checksum=checksum,
            method=proposal.method,
            scale_m_per_sfm_unit=scale,
            relative_uncertainty=proposal.relative_uncertainty,
            frames_used=proposal.frames_used,
        )

    def _build(
        self,
        job_id: str,
        source_visual: ProductArtifactRef,
        data: UserMetricInput,
        support: ProductArtifactRef | None,
    ) -> _Built:
        if data.distance_m < MIN_SEGMENT_M or data.check_distance_m < MIN_SEGMENT_M:
            raise ValueError("Đoạn A–B và C–D phải dài ít nhất 0,5 m để tỉ lệ đủ chính xác")
        tolerance = check_tolerance_m(data.distance_m, data.check_distance_m)
        if tolerance > MAX_TOLERANCE_RATIO * data.check_distance_m:
            raise ValueError("A–B quá ngắn so với C–D nên không kiểm chắc được; chọn vật dài hơn làm A–B")
        lidar = self._evidence(job_id, source_visual, data, support)
        estimate = self._estimate(job_id, source_visual, data)
        visual = self.visuals.load(source_visual)
        cameras = [pose.translation for pose in self.poses.load(visual.source_camera_poses).poses]
        scale = scale_from_distance((data.point_a, data.point_b), data.distance_m)
        frame = floor_frame(data.floor_points, data.point_a, data.point_b, scale, cameras)
        declaration = MeasurementDeclaration(
            job_id=job_id,
            source_visual_checksum=source_visual.artifact_checksum,
            input=data,
            lidar=lidar,
            estimate=estimate,
        )
        evidence = publish_json(
            self.writer, self.exists, job_id, "declarations", declaration, declaration.artifact_type
        )
        request = MetricRequest(
            source_visual=source_visual,
            anchor=DistanceAnchor(
                anchor_id=f"user-ab-{evidence.artifact_checksum.removeprefix('sha256:')[:12]}",
                source_master=visual.master,
                point_a=data.point_a,
                point_b=data.point_b,
                distance_m=data.distance_m,
                measurement_ref=evidence,
            ),
            frame=CanonicalFrameDeclaration(
                rotation_xyzw=frame.rotation_xyzw, translation_m=frame.translation_m, evidence_ref=evidence
            ),
            evidence_kind="real_measurement",
        )
        preview = MetricCanonicalizer(MetricDependencies(visuals=self.visuals, writer=self.writer)).preview(request)
        transform = preview.transform
        heights = [transform.apply_point(point)[2] for point in cameras]
        measured = math.dist(transform.apply_point(data.point_a), transform.apply_point(data.point_b))
        check = math.dist(transform.apply_point(data.check_a), transform.apply_point(data.check_b))
        error = abs(check - data.check_distance_m)
        summary = UserMetricPreview(
            preview_checksum=preview.checksum(),
            scale_m_per_sfm_unit=transform.scale_m_per_sfm_unit,
            floor_residual_m=frame.floor_residual_m,
            measured_distance_m=measured,
            camera_height_min_m=min(heights),
            camera_height_max_m=max(heights),
            distance_source=data.distance_source,
            check_measured_m=check,
            check_error_m=error,
            check_tolerance_m=tolerance,
            check_passed=error <= tolerance,
        )
        return _Built(preview, summary)

    def preview(
        self,
        job_id: str,
        source_visual: ProductArtifactRef,
        data: UserMetricInput,
        lidar_support: ProductArtifactRef | None = None,
    ) -> UserMetricPreview:
        """Tính trước, chưa xác nhận. `source_visual` là BrushVisualArtifact ref của preview."""
        return self._build(job_id, source_visual, data, lidar_support).summary

    def confirm(
        self,
        job_id: str,
        source_visual: ProductArtifactRef,
        data: UserMetricInput,
        preview_checksum: str,
        decision_ref: ProductArtifactRef,
        verify: Callable[[str, ProductArtifactRef], bool],
        lidar_support: ProductArtifactRef | None = None,
    ) -> ProductArtifactRef:
        """Xác nhận đúng preview đã xem; `verify(preview_checksum, decision_ref)` là authority của PRODUCT."""
        built = self._build(job_id, source_visual, data, lidar_support)
        if built.summary.preview_checksum != preview_checksum:
            raise ValueError("Điểm chọn hoặc khoảng cách đã đổi; xem trước lại rồi xác nhận")
        if not built.summary.check_passed:
            raise ValueError(
                f"Đoạn kiểm C–D lệch {built.summary.check_error_m * 100:.1f} cm, vượt ngưỡng "
                f"{built.summary.check_tolerance_m * 100:.1f} cm; đo hoặc chọn lại A/B, C/D"
            )
        canonicalizer = MetricCanonicalizer(
            MetricDependencies(
                visuals=self.visuals,
                writer=self.writer,
                verify_acceptance=lambda preview, acceptance: verify(preview.checksum(), acceptance.decision_ref),
            )
        )
        confirmation = canonicalizer.confirm(
            built.preview,
            MetricAcceptance(
                preview_checksum=preview_checksum, decision_ref=decision_ref, evidence_kind="real_measurement"
            ),
        )
        return canonicalizer.publish(confirmation, job_id)
