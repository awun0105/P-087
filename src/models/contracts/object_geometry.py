"""ObjectGS producer receipts; visual, surface and physics artifacts stay distinct."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier, JsonObject, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.object_membership import ObjectMembershipArtifact

Commit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


class ObjectSurfaceManifest(ContractModel):
    artifact_type: Literal["ObjectSurfaceManifest"] = "ObjectSurfaceManifest"
    schema_version: Literal["1.0"] = "1.0"
    object_id: Identifier
    objectgs_label_id: int = Field(ge=1, le=255, strict=True)
    surface_mesh_ref: ProductArtifactRef
    source_checkpoint_ref: ProductArtifactRef
    source_membership: ObjectMembershipArtifact
    upstream_commit: Commit
    canonical_world_from_training: Transform
    coordinate_frame: Literal["object_local"] = "object_local"
    distance_unit: Literal["m"] = "m"
    vertex_count: int = Field(ge=3, strict=True)
    triangle_count: int = Field(gt=0, strict=True)
    quality: JsonObject

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.surface_mesh_ref.artifact_type != "ObjectSurfaceMesh":
            raise ValueError("surface receipt requires ObjectSurfaceMesh")
        if self.source_checkpoint_ref.artifact_type != "ObjectGSCheckpoint":
            raise ValueError("surface receipt requires ObjectGSCheckpoint")
        if self.object_id not in self.source_membership.label_to_object_id.values():
            raise ValueError("surface object is absent from source membership")
        refs = (self.surface_mesh_ref, self.source_checkpoint_ref, self.source_membership.source_visual_ref)
        if len({ref.job_id for ref in refs}) != 1 or refs[0].job_id is None:
            raise ValueError("surface receipt refs must belong to the same job")
        return self


class ObjectAwareEnvironmentManifest(ContractModel):
    artifact_type: Literal["ObjectAwareEnvironmentManifest"] = "ObjectAwareEnvironmentManifest"
    schema_version: Literal["1.0"] = "1.0"
    source_geometry_ref: ProductArtifactRef
    collision_ref: ProductArtifactRef
    source_membership: ObjectMembershipArtifact
    removed_object_ids: list[Identifier]
    coordinate_frame: Literal["world"] = "world"
    distance_unit: Literal["m"] = "m"
    algorithm: Literal["object_aware_occupancy_v1"] = "object_aware_occupancy_v1"
    occupancy_checksum: Checksum
    provenance: JsonObject

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.removed_object_ids != sorted(set(self.removed_object_ids)):
            raise ValueError("removed_object_ids must be unique and sorted")
        if not set(self.removed_object_ids) <= set(self.source_membership.label_to_object_id.values()):
            raise ValueError("removed objects must belong to source membership")
        if self.collision_ref.artifact_type != "ObjectAwareEnvironmentCollision":
            raise ValueError("object-aware environment requires its own collision artifact")
        if self.source_geometry_ref != self.source_membership.source_geometry_ref:
            raise ValueError("original geometry must match membership source")
        refs = (self.source_geometry_ref, self.collision_ref, self.source_membership.source_visual_ref)
        if len({ref.job_id for ref in refs}) != 1 or refs[0].job_id is None:
            raise ValueError("environment refs must belong to the same job")
        return self
