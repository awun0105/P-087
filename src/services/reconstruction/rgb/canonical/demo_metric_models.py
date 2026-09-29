"""REC-06 internal demo inputs; LiDAR-assisted không phải RGB-only prediction.

Record này chứa correspondence đã chuẩn bị, không tự tìm cặp điểm hoặc xác nhận
alignment. Shared contracts và metric acceptance authority được giữ nguyên.
"""

import math
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import PreprocessingProvenance
from src.services.reconstruction.rgb.canonical.metric_models import (
    CanonicalFrameDeclaration,
    EvidenceKind,
    MetricPreview,
)
from src.services.reconstruction.rgb.pose.camera_pose import Vector3


class DemoMetricMode(StrEnum):
    """Ba trải nghiệm dùng chung measurement, chỉ fusion consume LiDAR geometry."""

    RGB_LIDAR_FUSION = "rgb_lidar_fusion"
    RGB_AUTO_SCALE_PROXY = "rgb_auto_scale_proxy"
    RGB_TWO_POINT = "rgb_two_point"


class DemoSceneIdentity(ContractModel):
    """Scene/traversal được verifier đối chiếu với source manifests, không suy từ URI."""

    scene_id: Identifier
    traversal_id: Identifier


class DemoLidarMeasurement(ContractModel):
    """Hai vị trí cùng vật lý, đo trong registered LiDAR frame có đơn vị mét."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["DemoLidarMeasurement"] = "DemoLidarMeasurement"
    identity: DemoSceneIdentity
    source_visual: ProductArtifactRef
    source_master: ProductArtifactRef
    source_lidar: ProductArtifactRef
    preprocessing_provenance: PreprocessingProvenance
    correspondence_ref: ProductArtifactRef
    frame: CanonicalFrameDeclaration
    rgb_points: tuple[Vector3, Vector3]
    lidar_points_m: tuple[Vector3, Vector3]
    evidence_kind: EvidenceKind

    @model_validator(mode="after")
    def _valid_measurement(self) -> Self:
        if self.source_lidar.artifact_type != "LiDARGeometryArtifact":
            raise ValueError("demo measurement requires registered LiDAR geometry")
        if self.source_lidar.producer_stage != StageId.LIDAR_INGEST:
            raise ValueError("demo measurement requires ingested LiDAR, not raw scans")
        if self.source_lidar.source_provenance != self.preprocessing_provenance.model_dump(mode="json"):
            raise ValueError("LiDAR preprocessing lineage differs from measurement")
        for pair in (self.rgb_points, self.lidar_points_m):
            distance = math.dist(*pair)
            if distance <= 0 or not math.isfinite(distance):
                raise ValueError("measurement requires distinct finite points")
        return self

    def distance_m(self) -> float:
        """Khoảng cách cảm biến, không phải accuracy hoặc independent evaluation."""
        return math.dist(*self.lidar_points_m)


class DemoMetricRequest(ContractModel):
    """Selection đổi phải có measurement mới; không fallback sang pair mặc định."""

    execution_scope: Literal["prepared_dataset_demo"]
    mode: DemoMetricMode
    identity: DemoSceneIdentity
    source_visual: ProductArtifactRef
    measurement_ref: ProductArtifactRef
    selected_rgb_points: tuple[Vector3, Vector3] | None = None

    @model_validator(mode="after")
    def _selection_mode(self) -> Self:
        if (self.mode == DemoMetricMode.RGB_TWO_POINT) != (self.selected_rgb_points is not None):
            raise ValueError("selected RGB points are required only in two-point mode")
        return self


class DemoMetricPreview(ContractModel):
    """Preview dùng thử; geometry ref là composition input, chưa là fused output."""

    request: DemoMetricRequest
    metric_preview: MetricPreview
    suggested_distance_m: FiniteFloat = Field(gt=0)
    assistance: Literal["lidar_assisted_demo"] = "lidar_assisted_demo"
    independent_rgb_only: Literal[False] = False
    preprocessing_provenance: PreprocessingProvenance
    lidar_geometry_for_composition: ProductArtifactRef | None
