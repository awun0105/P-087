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
from src.models.contracts.object_membership import ObjectMembershipArtifact

PositiveDimension = Annotated[FiniteFloat, Field(gt=0)]


class ColliderType(StrEnum):
    """Collider representations allowed by the P0 contract."""

    AABB = "AABB"
    OBB = "OBB"
    CONVEX_HULL = "CONVEX_HULL"
    SIMPLIFIED_MESH = "SIMPLIFIED_MESH"
    # Pipeline v2 (ADR 0007): rigid body động không dùng được triangle mesh trong Isaac → nhiều mảnh
    # lồi (CoACD); `geometry_ref` trỏ tới file chứa các mảnh.
    CONVEX_DECOMPOSITION = "CONVEX_DECOMPOSITION"


class ColliderSpec(ContractModel):
    """Physics representation attached to a canonical SceneObject."""

    collider_id: Identifier
    collider_type: ColliderType
    local_transform: Transform
    dimensions_xyz_m: tuple[float, float, float] | None = None
    geometry_ref: ProductArtifactRef | None = None
    parameters: JsonObject
    provenance: JsonObject


class MassSource(StrEnum):
    """Khối lượng lấy từ đâu — để Reviewer biết số nào là đo, số nào là mặc định."""

    CATALOG_DEFAULT = "catalog_default"
    CATALOG_DENSITY = "catalog_density"
    USER = "user"
    ASSET = "asset"


def _absent(value: object) -> bool:
    """Trường tuỳ chọn thêm sau (pipeline v2) không ghi khi rỗng, để checksum SceneIR cũ giữ nguyên."""
    return value is None


class SourceCollisionMembership(ContractModel):
    """Triangle indices trong đúng bytes collision mesh do `source_geometry_ref` chỉ tới.

    An empty list is a valid audited ownership state after every source triangle moved elsewhere.
    """

    artifact_type: Literal["SourceCollisionMembership"] = "SourceCollisionMembership"
    schema_version: Literal["1.0"] = "1.0"
    object_id: Identifier
    source_geometry_ref: ProductArtifactRef
    extraction_revision: Identifier
    triangle_indices: list[Annotated[int, Field(ge=0, strict=True)]]

    @model_validator(mode="after")
    def _require_unique_ordered_indices(self) -> Self:
        if self.triangle_indices != sorted(set(self.triangle_indices)):
            raise ValueError("triangle_indices must be unique and sorted")
        return self


class SourceCollisionRegion(ContractModel):
    """Ownership của object trên mesh collision nguồn, bound vào pose extraction và scene revision."""

    schema_version: Literal["1.0"] = "1.0"
    object_id: Identifier
    source_geometry_ref: ProductArtifactRef
    extraction_revision: Identifier
    source_transform: Transform
    region_kind: Literal["triangle_indices", "source_obb"]
    region_ref: ProductArtifactRef | None = Field(default=None, exclude_if=_absent)
    source_obb_dimensions_xyz_m: tuple[PositiveDimension, PositiveDimension, PositiveDimension] | None = Field(
        default=None, exclude_if=_absent
    )

    @model_validator(mode="after")
    def _validate_region_representation(self) -> Self:
        if self.source_transform.parent_frame != "world" or self.source_transform.local_frame != self.object_id:
            raise ValueError("source_transform must bind world to the owned object frame")
        if self.region_kind == "triangle_indices":
            if self.region_ref is None or self.region_ref.artifact_type != "SourceCollisionMembership":
                raise ValueError("triangle_indices region requires a SourceCollisionMembership region_ref")
            if self.source_obb_dimensions_xyz_m is not None:
                raise ValueError("triangle_indices region cannot also declare OBB dimensions")
        elif self.region_ref is not None or self.source_obb_dimensions_xyz_m is None:
            raise ValueError("source_obb region requires dimensions and cannot declare a membership ref")
        return self


class ObjectPhysics(ContractModel):
    """Thuộc tính vật lý của một vật cho Isaac (RigidBody, Mass, Physics Material; ADR 0007).

    `dynamic=False`: vật cố định (kệ, cột) — chỉ có collider tĩnh, không RigidBody.
    """

    dynamic: bool
    mass_kg: PositiveDimension | None = None
    mass_source: MassSource | None = None
    density_kg_m3: PositiveDimension | None = None
    static_friction: Annotated[FiniteFloat, Field(ge=0)]
    dynamic_friction: Annotated[FiniteFloat, Field(ge=0)]
    restitution: Annotated[FiniteFloat, Field(ge=0, le=1)]
    provenance: JsonObject

    @model_validator(mode="after")
    def _dynamic_needs_mass(self) -> Self:
        if self.dynamic and (self.mass_kg is None or self.mass_source is None):
            raise ValueError("vật động cần mass_kg và mass_source")
        return self


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
    semantic_class: str | None = None
    tags: list[str] = Field(default_factory=list)
    provenance: JsonObject
    physics: ObjectPhysics | None = Field(default=None, exclude_if=_absent)
    source_collision: SourceCollisionRegion | None = Field(default=None, exclude_if=_absent)

    @model_validator(mode="after")
    def _validate_representation_binding(self) -> Self:
        if self.transform.local_frame != self.local_frame:
            raise ValueError("SceneObject.local_frame must match transform.local_frame")
        if self.collider is not None and self.collider.local_transform.parent_frame != self.local_frame:
            raise ValueError("collider local offset must be parented to SceneObject.local_frame")
        if self.source_collision is not None:
            if self.source_collision.object_id != self.id:
                raise ValueError("source collision ownership object_id must match SceneObject.id")
            if self.origin == SceneObjectOrigin.USER_ADDED:
                raise ValueError("user-added objects cannot own reconstructed source collision regions")
        if self.origin == SceneObjectOrigin.USER_ADDED:
            if self.asset_ref is None and self.primitive_dimensions_xyz_m is None:
                raise ValueError("user_added object requires asset_ref or primitive_dimensions_xyz_m")
        return self


class SceneEnvironment(ContractModel):
    """Static environment representation for a scene revision."""

    visual_ref: ProductArtifactRef | None = None
    geometry_ref: ProductArtifactRef
    collider_ref: ProductArtifactRef | None = None
    # Exact source collision and selection identities; collider_ref may later refer to a carved result.
    collision_source_ref: ProductArtifactRef | None = Field(default=None, exclude_if=_absent)
    collision_selection_ref: ProductArtifactRef | None = Field(default=None, exclude_if=_absent)
    # Bản 3DGS gốc (PLY) của nền cho bộ xuất USD; `visual_ref` là bản nén cho trình duyệt (SOG).
    visual_master_ref: ProductArtifactRef | None = Field(default=None, exclude_if=_absent)
    # Row ownership is optional for legacy scenes and embedded so each SceneIR revision binds its exact map.
    membership: ObjectMembershipArtifact | None = Field(default=None, exclude_if=_absent)

    @model_validator(mode="after")
    def _validate_collision_selection_binding(self) -> Self:
        source_ref = self.collision_source_ref
        selection_ref = self.collision_selection_ref
        if source_ref is None and selection_ref is None:
            return self
        if source_ref is None or selection_ref is None:
            raise ValueError("collision_source_ref and collision_selection_ref must be set together")
        if self.collider_ref is None:
            raise ValueError("a selected collision source requires an effective collider_ref")
        if selection_ref.artifact_type != "CollisionSourceSelection":
            raise ValueError("collision_selection_ref must reference a CollisionSourceSelection artifact")
        scene_job_id = _artifact_job_id(self.geometry_ref)
        if _artifact_job_id(source_ref) != scene_job_id or _artifact_job_id(selection_ref) != scene_job_id:
            raise ValueError("collision source and selection must belong to the SceneIR job")
        return self


def _artifact_job_id(reference: ProductArtifactRef) -> str:
    """Use the logical URI as the job scope and reject contradictory optional metadata."""
    uri_job_id = reference.artifact_uri.removeprefix("artifact://jobs/").partition("/")[0]
    if reference.job_id is not None and reference.job_id != uri_job_id:
        raise ValueError("artifact job_id must match its logical URI")
    return uri_job_id


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
            if (
                item.source_collision is not None
                and item.source_collision.source_geometry_ref != self.environment.geometry_ref
            ):
                raise ValueError("source collision ownership must reference the SceneIR environment geometry")
        return self
