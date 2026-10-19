"""Versioned ownership map from source Gaussian rows to scene objects."""

from math import isfinite, pi
from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, StrictInt, model_validator

from src.models.contracts.artifacts import Checksum, ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem


class ObjectMembershipArtifact(ContractModel):
    """Scene-embedded manifest for an immutable little-endian Gaussian label array."""

    artifact_type: Literal["ObjectMembershipArtifact"] = "ObjectMembershipArtifact"
    schema_version: Literal["1.0"] = "1.0"
    source_visual_ref: ProductArtifactRef
    source_geometry_ref: ProductArtifactRef
    extraction_revision: Identifier
    coordinate_system: CoordinateSystem
    gaussian_count: int = Field(gt=0, strict=True)
    labels_ref: ProductArtifactRef
    labels_encoding: Literal["little-endian-int32"] = "little-endian-int32"
    background_label: Literal[-1] = -1
    label_to_object_id: dict[str, Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_identity_and_labels(self) -> Self:
        refs = (self.source_visual_ref, self.source_geometry_ref, self.labels_ref)
        job_ids = {ref.job_id for ref in refs}
        if len(job_ids) != 1 or None in job_ids:
            raise ValueError("membership source and label refs must belong to the same job")
        if self.labels_ref.artifact_type != "ObjectMembershipLabels":
            raise ValueError("labels_ref must point to ObjectMembershipLabels bytes")

        keys = list(self.label_to_object_id)
        parsed: list[int] = []
        for key in keys:
            if not key.isascii() or not key.isdigit() or str(int(key)) != key:
                raise ValueError("membership labels must be canonical non-negative integer strings")
            parsed.append(int(key))
        if parsed != sorted(set(parsed)):
            raise ValueError("label_to_object_id must have unique labels in numeric order")
        return self


class MembershipCommandBase(ContractModel):
    """Optimistic concurrency and membership identity required by correction commands."""

    expected_scene_revision: Identifier
    membership_checksum: Checksum


class ObjectMembershipMergeCommand(MembershipCommandBase):
    """Merge candidate memberships while preserving the explicit primary identity."""

    primary_object_id: Identifier
    secondary_object_ids: list[Identifier] = Field(min_length=1, max_length=60)
    semantic_class_source_object_id: Identifier | None = None

    @model_validator(mode="after")
    def _require_unique_secondary_objects(self) -> Self:
        if len(set(self.secondary_object_ids)) != len(self.secondary_object_ids):
            raise ValueError("secondary_object_ids must be unique")
        if self.primary_object_id in self.secondary_object_ids:
            raise ValueError("primary object cannot also be secondary")
        selected_ids = {self.primary_object_id, *self.secondary_object_ids}
        if (
            self.semantic_class_source_object_id is not None
            and self.semantic_class_source_object_id not in selected_ids
        ):
            raise ValueError("semantic class source must be one of the merged objects")
        return self


class SourceGaussianROI(ContractModel):
    """Finite, bounded AABB selection in canonical world meters over source rows."""

    min_xyz_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    max_xyz_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]

    @model_validator(mode="after")
    def _require_bounded_non_degenerate_region(self) -> Self:
        if any(abs(value) > 1_000_000 for value in (*self.min_xyz_m, *self.max_xyz_m)):
            raise ValueError("source ROI must remain within the supported ±1,000,000 m bound")
        if any(low >= high for low, high in zip(self.min_xyz_m, self.max_xyz_m, strict=True)):
            raise ValueError("source ROI bounds must be strictly increasing on every axis")
        if not all(isfinite(value) for value in (*self.min_xyz_m, *self.max_xyz_m)):
            raise ValueError("source ROI bounds must be finite")
        return self


class ObjectMembershipReassignCommand(MembershipCommandBase):
    """Move selected source Gaussian rows between an object and the background."""

    region: SourceGaussianROI | None = None
    source_gaussian_indices: list[StrictInt] | None = Field(default=None, min_length=1, max_length=250_000)
    source_visual_checksum: Checksum | None = None
    source_object_id: Identifier | None
    target_object_id: Identifier | None

    @model_validator(mode="after")
    def _require_distinct_owners(self) -> Self:
        if (self.region is None) == (self.source_gaussian_indices is None):
            raise ValueError("provide exactly one source ROI or source Gaussian index selection")
        if self.source_gaussian_indices is not None:
            if self.source_visual_checksum is None:
                raise ValueError("source Gaussian selection requires source_visual_checksum")
            if self.source_gaussian_indices != sorted(set(self.source_gaussian_indices)) or any(
                index < 0 for index in self.source_gaussian_indices
            ):
                raise ValueError("source Gaussian indices must be sorted, unique and non-negative")
        if self.source_object_id is None and self.target_object_id is None:
            raise ValueError("a Gaussian region cannot move from background back to background")
        if self.source_object_id == self.target_object_id:
            raise ValueError("source and target owners must differ; null denotes background")
        return self


class ObjectMembershipPreview(ContractModel):
    """Read-only effective selection after ownership and background floor protection."""

    scene_revision: Identifier
    membership_checksum: Checksum
    source_visual_checksum: Checksum
    source_object_id: Identifier | None
    target_object_id: Identifier | None
    affected_object_ids: list[Identifier]
    gaussian_count: int = Field(gt=0, strict=True)
    protected_count: int = Field(ge=0, strict=True)
    wrong_owner_count: int = Field(ge=0, strict=True)
    source_gaussian_indices: list[StrictInt] = Field(min_length=1, max_length=250_000)
    remaining_gaussians: dict[Identifier, int]


#: Nửa kích thước box theo trục cục bộ: khoảng đóng [0.005, 20] m (architecture §7.3).
HalfExtentM = Annotated[FiniteFloat, Field(ge=0.005, le=20)]


class RegionBox(ContractModel):
    """Object-local box that adds or subtracts source rows; yaw turns right-handed about +Z."""

    op: Literal["add", "subtract"]
    center_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    half_extents_m: tuple[HalfExtentM, HalfExtentM, HalfExtentM]
    yaw_rad: FiniteFloat = Field(default=0.0, ge=-2 * pi, le=2 * pi)


class ObjectRegionCommand(MembershipCommandBase):
    """Box edit of one object's source rows, shared by preview and apply."""

    boxes: list[RegionBox] = Field(min_length=1, max_length=16)
    claim_from: list[Identifier] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def _require_add_box_and_unique_claims(self) -> Self:
        if not any(box.op == "add" for box in self.boxes):
            raise ValueError("region command requires at least one add box")
        if len(set(self.claim_from)) != len(self.claim_from):
            raise ValueError("claim_from must not repeat object ids")
        return self
