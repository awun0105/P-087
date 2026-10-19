"""Capability contract for the two USD package builders."""

from __future__ import annotations

import math
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field

from src.models.contracts.artifacts import ContractModel, ProductArtifactRef
from src.models.contracts.scene import ColliderType, SceneIR, SceneObject, SceneObjectState
from src.services.orchestration.artifacts.checksum import verify_file_checksum
from src.services.orchestration.artifacts.errors import ArtifactStoreError
from src.services.scene.representation_composition import scene_representations
from src.services.scene.representation_integrity import representation_issues
from src.services.simulation.mesh_geometry import MeshValidationError, load_mesh_parts


class EffectiveExportMode(StrEnum):
    """Builder implementation selected from the scene's requirements."""

    LEGACY_BOX = "legacy_box"
    HYBRID = "hybrid"


class ExportCapabilityStatus(StrEnum):
    """Whether the selected builder can preserve every requested scene feature."""

    SUPPORTED = "supported"
    BLOCKED = "blocked"


class RuntimeQualificationStatus(StrEnum):
    """Whether the USD runtime was required and passed the feature probe."""

    NOT_REQUIRED = "not_required"
    QUALIFIED = "qualified"
    FAILED = "failed"


class ExportRequirements(ContractModel):
    """Minimal builder-facing projection of SceneIR requirements."""

    collider_types: list[ColliderType] = Field(default_factory=list)
    static_physics: bool = False
    dynamic_physics: bool = False
    local_collider_offsets: bool = False
    hybrid_visuals: bool = False
    external_assets: bool = False


class ExportCapabilityBlocker(ContractModel):
    """A typed reason why an exporter cannot meet the requested scene contract."""

    code: str
    message: str
    affected_object_ids: list[str] = Field(default_factory=list)


class ExportCapabilityReport(ContractModel):
    """Persisted evidence tying a package decision to one exact SceneIR revision."""

    schema_version: Literal["1.0"] = "1.0"
    scene_revision: str
    scene_ir_checksum: str
    status: ExportCapabilityStatus
    requested_mode: Literal["auto"] = "auto"
    effective_mode: EffectiveExportMode
    builder_version: str
    runtime_qualification: RuntimeQualificationStatus
    runtime_version: str | None = None
    requirements: ExportRequirements
    blockers: list[ExportCapabilityBlocker] = Field(default_factory=list)
    #: Non-blocking facts the user should know about; the export is valid with or without them.
    notices: list[ExportCapabilityBlocker] = Field(default_factory=list)


ResolveArtifact = Callable[[ProductArtifactRef], Path]
_USD_ASSET_SUFFIXES = {".usd", ".usda", ".usdc", ".usdz"}


def _has_non_identity_offset(obj: SceneObject) -> bool:
    collider = obj.collider
    if collider is None:
        return False
    transform = collider.local_transform
    translation = transform.translation_xyz
    rotation = transform.rotation_quaternion_xyzw
    translation_is_zero = all(abs(value) <= 1e-8 for value in translation)
    rotation_is_identity = all(abs(value) <= 1e-8 for value in rotation[:3]) and abs(abs(rotation[3]) - 1.0) <= 1e-8
    return not (translation_is_zero and rotation_is_identity)


def _uses_external_asset(obj: SceneObject) -> bool:
    """A sealed USD artifact the package must carry; a catalog `asset_url` is provenance, not a dependency."""
    return obj.asset_ref is not None


def catalog_asset_provenance(obj: SceneObject) -> dict[str, str] | None:
    """Catalog family and public Isaac asset URL of an object that is exported as its box proxy."""
    url = obj.provenance.get("asset_url")
    if obj.asset_ref is not None or not isinstance(url, str):
        return None
    family = obj.provenance.get("catalog_family")
    return {"family": family if isinstance(family, str) else "", "asset_url": url}


def _resolve_usd_asset(ref: ProductArtifactRef, resolve_artifact: ResolveArtifact | None) -> str | None:
    """Accept only checksum-verified USD files that can be copied into the package."""
    if PurePosixPath(ref.artifact_uri).suffix.lower() not in _USD_ASSET_SUFFIXES:
        return "EXTERNAL_ASSET_FORMAT_UNSUPPORTED"
    if resolve_artifact is None:
        return "EXTERNAL_ASSET_RESOLVER_MISSING"
    try:
        path = resolve_artifact(ref)
        if not path.is_file():
            return "EXTERNAL_ASSET_REF_INVALID"
        verify_file_checksum(path, ref.artifact_checksum)
    except (ArtifactStoreError, OSError, ValueError):
        return "EXTERNAL_ASSET_REF_INVALID"
    return None


def export_requirements(scene: SceneIR) -> ExportRequirements:
    """Derive requirements from authored SceneIR fields, not builder availability."""
    dispositions = {item.object_id: item for item in scene_representations(scene)}
    exported = [item for item in scene.objects if dispositions[item.id].export_as_object]
    collider_types = sorted({item.collider.collider_type for item in exported if item.collider is not None}, key=str)
    return ExportRequirements(
        collider_types=collider_types,
        static_physics=any(item.physics is not None and not item.physics.dynamic for item in exported),
        dynamic_physics=any(item.physics is not None and item.physics.dynamic for item in exported),
        local_collider_offsets=any(_has_non_identity_offset(item) for item in exported),
        hybrid_visuals=any(item.source_visual_required for item in dispositions.values())
        or scene.environment.visual_master_ref is not None
        or any(item.visual_ref is not None and item.visual_ref.artifact_type == "ObjectGaussians" for item in exported),
        external_assets=any(_uses_external_asset(item) for item in exported),
    )


def select_export_mode(requirements: ExportRequirements) -> EffectiveExportMode:
    """Choose the least capable builder that still needs to express the full request."""
    legacy_colliders = {ColliderType.AABB, ColliderType.OBB}
    if (
        requirements.hybrid_visuals
        or requirements.static_physics
        or requirements.dynamic_physics
        or requirements.external_assets
        or any(collider_type not in legacy_colliders for collider_type in requirements.collider_types)
    ):
        return EffectiveExportMode.HYBRID
    return EffectiveExportMode.LEGACY_BOX


def _blocker(code: str, message: str, objects: list[str] | None = None) -> ExportCapabilityBlocker:
    return ExportCapabilityBlocker(code=code, message=message, affected_object_ids=sorted(set(objects or [])))


def _resolve_mesh(ref: ProductArtifactRef | None, resolve_artifact: ResolveArtifact | None) -> str | None:
    """Return a structural blocker code for an unresolved or empty required mesh."""
    if ref is None:
        return "COLLIDER_GEOMETRY_REF_MISSING"
    if resolve_artifact is None:
        return "COLLIDER_GEOMETRY_RESOLVER_MISSING"
    try:
        path = resolve_artifact(ref)
        load_mesh_parts(path)
    except MeshValidationError as error:
        return error.code
    except (ArtifactStoreError, OSError, ValueError, TypeError):
        return "COLLIDER_GEOMETRY_REF_INVALID"
    return None


def _resolve_required_ref(ref: ProductArtifactRef, resolve_artifact: ResolveArtifact | None) -> bool:
    """Verify that a referenced visual is present and its bytes match the declared checksum."""
    if resolve_artifact is None:
        return False
    try:
        path = resolve_artifact(ref)
        if not path.is_file():
            return False
        verify_file_checksum(path, ref.artifact_checksum)
    except (ArtifactStoreError, OSError, ValueError):
        return False
    return True


def assess_export_capabilities(
    scene: SceneIR,
    *,
    runtime_qualified: bool,
    runtime_version: str | None = None,
    resolve_artifact: ResolveArtifact | None = None,
) -> ExportCapabilityReport:
    """Compare exact scene requirements with implemented USD behavior.

    The legacy writer keeps only static AABB/OBB colliders without ObjectPhysics or
    external asset requirements. The hybrid writer is qualified separately and
    authors local-frame boxes, validated convex pieces, ObjectPhysics, and sealed
    USD assets whose dependency paths remain inside the package.
    """
    requirements = export_requirements(scene)
    mode = select_export_mode(requirements)
    blockers: list[ExportCapabilityBlocker] = [
        _blocker(code, "Visual representation cannot be reconstructed from verified source evidence.", [object_id])
        for object_id, code in representation_issues(scene, resolve_artifact)
    ]
    dispositions = {item.object_id: item for item in scene_representations(scene)}
    exported = [item for item in scene.objects if dispositions[item.id].export_as_object]

    if mode == EffectiveExportMode.HYBRID and not runtime_qualified:
        blockers.append(
            _blocker(
                "USD_RUNTIME_UNQUALIFIED",
                "The configured USD Python runtime did not pass the required API capability probe.",
            )
        )

    if mode == EffectiveExportMode.LEGACY_BOX:
        if requirements.hybrid_visuals:
            blockers.append(
                _blocker("HYBRID_VISUALS_UNSUPPORTED", "The legacy box exporter cannot author Gaussian visuals.")
            )
        for item in exported:
            if item.state == SceneObjectState.CONFIRMED and item.collider is None:
                blockers.append(
                    _blocker("COLLIDER_MISSING", "A confirmed object requires an explicit collider.", [item.id])
                )
            if item.physics is not None:
                blockers.append(
                    _blocker(
                        "OBJECT_PHYSICS_UNSUPPORTED", "The legacy exporter cannot preserve ObjectPhysics.", [item.id]
                    )
                )
            if _uses_external_asset(item):
                blockers.append(
                    _blocker(
                        "EXTERNAL_ASSET_UNSUPPORTED", "The legacy exporter cannot include external assets.", [item.id]
                    )
                )
            if item.collider is not None and item.collider.collider_type not in {ColliderType.AABB, ColliderType.OBB}:
                blockers.append(
                    _blocker(
                        "COLLIDER_REPRESENTATION_UNSUPPORTED",
                        f"The legacy exporter cannot preserve {item.collider.collider_type} geometry.",
                        [item.id],
                    )
                )
            if item.collider is not None and (
                item.collider.dimensions_xyz_m is None
                or any(not math.isfinite(value) or value <= 0 for value in item.collider.dimensions_xyz_m)
            ):
                blockers.append(
                    _blocker(
                        "COLLIDER_DIMENSIONS_INVALID", "A box collider requires finite positive dimensions.", [item.id]
                    )
                )
    else:
        visual_refs = [
            ref
            for ref in [
                scene.environment.visual_master_ref,
                *(
                    item.visual_ref
                    for item in exported
                    if item.visual_ref and item.visual_ref.artifact_type == "ObjectGaussians"
                ),
            ]
            if ref is not None
        ]
        if requirements.hybrid_visuals:
            missing_visuals = [ref for ref in visual_refs if not _resolve_required_ref(ref, resolve_artifact)]
            if missing_visuals:
                blockers.append(
                    _blocker(
                        "HYBRID_VISUAL_REF_INVALID",
                        "A required Gaussian artifact is missing or its bytes do not match the declared checksum.",
                    )
                )
        for item in exported:
            if item.asset_ref is None:
                continue
            issue = _resolve_usd_asset(item.asset_ref, resolve_artifact)
            if issue:
                message = (
                    "The referenced asset must be a checksum-verified USD file with a supported package extension."
                    if issue == "EXTERNAL_ASSET_FORMAT_UNSUPPORTED"
                    else "The referenced USD asset is missing or its bytes do not match the declared checksum."
                )
                blockers.append(_blocker(issue, message, [item.id]))
        for item in exported:
            collider = item.collider
            if collider is None:
                if item.state.value == "CONFIRMED":
                    blockers.append(
                        _blocker(
                            "COLLIDER_MISSING", "A confirmed hybrid object requires an explicit collider.", [item.id]
                        )
                    )
                continue
            if collider.collider_type == ColliderType.CONVEX_DECOMPOSITION:
                issue = _resolve_mesh(collider.geometry_ref, resolve_artifact)
                if issue:
                    blockers.append(
                        _blocker(
                            issue,
                            "The convex collider reference is missing, invalid, or has no valid topology.",
                            [item.id],
                        )
                    )
            elif collider.collider_type in {ColliderType.AABB, ColliderType.OBB}:
                if collider.dimensions_xyz_m is None:
                    blockers.append(
                        _blocker(
                            "COLLIDER_DIMENSIONS_INVALID",
                            "The hybrid box exporter requires finite positive collider dimensions.",
                            [item.id],
                        )
                    )
                elif any(not math.isfinite(float(value)) or float(value) <= 0 for value in collider.dimensions_xyz_m):
                    blockers.append(
                        _blocker(
                            "COLLIDER_DIMENSIONS_INVALID",
                            "The hybrid box exporter requires finite positive collider dimensions.",
                            [item.id],
                        )
                    )
            else:
                blockers.append(
                    _blocker(
                        "COLLIDER_REPRESENTATION_UNSUPPORTED",
                        f"The current hybrid adapter cannot preserve {collider.collider_type} geometry.",
                        [item.id],
                    )
                )
            if (
                item.physics is not None
                and item.physics.dynamic
                and (item.physics.mass_kg is None or item.physics.mass_source is None)
            ):
                blockers.append(
                    _blocker(
                        "DYNAMIC_MASS_MISSING", "A dynamic object requires both mass_kg and mass_source.", [item.id]
                    )
                )

    unique: dict[tuple[str, tuple[str, ...]], ExportCapabilityBlocker] = {}
    for issue in blockers:
        unique[(issue.code, tuple(issue.affected_object_ids))] = issue
    blockers = sorted(unique.values(), key=lambda item: (item.code, item.affected_object_ids))
    catalog_ids = [item.id for item in exported if catalog_asset_provenance(item) is not None]
    notices = (
        [
            _blocker(
                "CATALOG_ASSET_EXPORTED_AS_BOX",
                "Vật từ danh mục Isaac được xuất bằng collider hộp đúng kích thước và vật lý đã khai báo. Hình asset "
                "không nhúng vào gói vì bytes không niêm phong được; nguồn asset ghi ở customData real2sim:catalog.",
                catalog_ids,
            )
        ]
        if catalog_ids
        else []
    )
    return ExportCapabilityReport(
        scene_revision=scene.scene_revision,
        scene_ir_checksum=scene.scene_ir_checksum,
        status=ExportCapabilityStatus.BLOCKED if blockers else ExportCapabilityStatus.SUPPORTED,
        effective_mode=mode,
        builder_version="usd-export-capabilities-v3",
        runtime_qualification=(
            RuntimeQualificationStatus.NOT_REQUIRED
            if mode == EffectiveExportMode.LEGACY_BOX
            else RuntimeQualificationStatus.QUALIFIED
            if runtime_qualified
            else RuntimeQualificationStatus.FAILED
        ),
        runtime_version=runtime_version,
        requirements=requirements,
        blockers=blockers,
        notices=notices,
    )


def validate_builder_mode(scene: SceneIR, mode: EffectiveExportMode) -> None:
    """Fail closed when a low-level CandidateBuildRequest bypasses orchestration."""
    if any(item.readiness_blockers for item in scene_representations(scene)):
        raise ValueError("visual representation policy has unresolved blockers")
    requirements = export_requirements(scene)
    inferred_mode = select_export_mode(requirements)
    if mode == EffectiveExportMode.LEGACY_BOX and inferred_mode != mode:
        raise ValueError(f"USD build mode '{mode}' does not satisfy required mode '{inferred_mode}'")
    if mode == EffectiveExportMode.LEGACY_BOX:
        for item in scene.objects:
            if not item.active:
                continue
            if item.state == SceneObjectState.CONFIRMED and item.collider is None:
                raise ValueError(f"legacy USD exporter requires a collider for confirmed object '{item.id}'")
            if item.physics is not None or _uses_external_asset(item):
                raise ValueError(f"legacy USD exporter cannot preserve physics or asset dependencies for '{item.id}'")
            if item.collider is not None and item.collider.collider_type not in {ColliderType.AABB, ColliderType.OBB}:
                raise ValueError(
                    f"legacy USD exporter cannot preserve collider '{item.collider.collider_type}' for '{item.id}'"
                )
            if item.collider is not None and (
                item.collider.dimensions_xyz_m is None
                or any(not math.isfinite(value) or value <= 0 for value in item.collider.dimensions_xyz_m)
            ):
                raise ValueError(f"legacy USD exporter requires finite positive collider dimensions for '{item.id}'")
