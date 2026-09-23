"""Canonical SceneIR, SceneObject and collider contracts."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from src.models.contracts.artifacts import (
    Checksum,
    ContractModel,
    Identifier,
    JsonObject,
    ProductArtifactRef,
    SchemaVersion,
)
from src.models.contracts.coordinates import CoordinateSystem, MetricScale, Transform

PositiveDimension = Annotated[FiniteFloat, Field(gt=0)]


class ColliderType(StrEnum):
    """Collider representations allowed by the P0 contract."""

    AABB = "AABB"
    OBB = "OBB"
    CONVEX_HULL = "CONVEX_HULL"
    SIMPLIFIED_MESH = "SIMPLIFIED_MESH"


class ColliderSpec(ContractModel):
    """Physics representation attached to a canonical SceneObject."""

    collider_id: Identifier
    collider_type: ColliderType
    local_transform: Transform
    dimensions_xyz_m: tuple[float, float, float] | None = None
    geometry_ref: ProductArtifactRef | None = None
    parameters: JsonObject
    provenance: JsonObject


class SceneObjectOrigin(StrEnum):
    """Supported origins for a SceneObject."""

    RECONSTRUCTED = "reconstructed"
    USER_ADDED = "user_added"


class SceneObjectState(StrEnum):
    """Object-confirmation state; review state lives outside SceneIR."""

    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"


class SceneObject(ContractModel):
    """Editable object with one canonical parent-from-local transform."""

    id: Identifier
    name: str
    state: SceneObjectState
    origin: SceneObjectOrigin
    active: bool
    local_frame: Identifier
    transform: Transform
    visual_ref: ProductArtifactRef | None = None
    geometry_ref: ProductArtifactRef
    asset_ref: ProductArtifactRef | None = None
    primitive_dimensions_xyz_m: tuple[PositiveDimension, PositiveDimension, PositiveDimension] | None = None
    collider: ColliderSpec | None = None
    provenance: JsonObject

    @model_validator(mode="after")
    def _validate_representation_binding(self) -> Self:
        if self.transform.local_frame != self.local_frame:
            raise ValueError("SceneObject.local_frame must match transform.local_frame")
        if self.collider is not None and self.collider.local_transform.parent_frame != self.local_frame:
            raise ValueError("collider local offset must be parented to SceneObject.local_frame")
        if self.origin == SceneObjectOrigin.USER_ADDED:
            if self.asset_ref is None and self.primitive_dimensions_xyz_m is None:
                raise ValueError("user_added object requires asset_ref or primitive_dimensions_xyz_m")
        return self


class SceneEnvironment(ContractModel):
    """Static environment representation for a scene revision."""

    visual_ref: ProductArtifactRef | None = None
    geometry_ref: ProductArtifactRef
    collider_ref: ProductArtifactRef | None = None


class SceneIR(ContractModel):
    """Project-owned scene content; workflow/review state is deliberately absent."""

    artifact_type: Literal["SceneIR"]
    schema_version: SchemaVersion
    scene_id: Identifier
    scene_revision: Identifier
    coordinate_system: CoordinateSystem
    metric_scale: MetricScale
    environment: SceneEnvironment
    objects: list[SceneObject]
    provenance: JsonObject
    scene_ir_checksum: Checksum

    @model_validator(mode="after")
    def _require_unique_object_ids(self) -> Self:
        seen: set[str] = set()
        for item in self.objects:
            if item.id in seen:
                raise ValueError(f"duplicate SceneObject.id in SceneIR: {item.id}")
            seen.add(item.id)
        return self
