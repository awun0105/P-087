"""Select a qualified LiDAR collision candidate with source-bound ownership."""

from __future__ import annotations

import io
from typing import Literal

import numpy as np
import trimesh
from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ArtifactDataClass, ContractModel, Identifier, ProductArtifactRef
from src.models.contracts.collision_quality import (
    CollisionAlignmentQAKind,
    CollisionInputMode,
    CollisionSourceMode,
    seal_collision_source_selection,
)
from src.models.contracts.identity import canonical_json_bytes
from src.models.contracts.manifests import StageId
from src.models.contracts.scene import SceneIR, SceneObjectOrigin, SourceCollisionMembership, SourceCollisionRegion
from src.services.orchestration.artifacts.checksum import sha256_bytes
from src.services.orchestration.artifacts.errors import ArtifactAlreadyExistsError, ArtifactStoreError
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.errors import SceneEditRejectedError, SceneRevisionConflictError
from src.services.orchestration.scene.models import SceneEditResult
from src.services.reconstruction.adapters.lidar_collision import LidarCollisionBuildReport
from src.services.reconstruction.lidar.collision_candidate_publisher import (
    LidarCollisionCandidateManifest,
    load_lidar_collision_eligibility_inputs,
)
from src.services.reconstruction.lidar.collision_eligibility import evaluate_lidar_collision_eligibility
from src.services.scene.collision_ownership import SourceCollisionOwnershipError, source_triangle_ownership
from src.services.simulation.colliders.carve import CarveBox, triangle_mask_in_box


class LidarObjectCollisionCoverage(ContractModel):
    """Measured candidate-face coverage for one reconstructed object region."""

    object_id: Identifier
    candidate_triangle_count: int = Field(ge=0, strict=True)
    owned_triangle_count: int = Field(ge=0, strict=True)
    ambiguous_triangle_count: int = Field(ge=0, strict=True)
    coverage_fraction: FiniteFloat = Field(ge=0, le=1)


class LidarCollisionOwnershipReport(ContractModel):
    """Coverage diagnostics bound to one exact candidate source and scene revision."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["LidarCollisionOwnershipReport"] = "LidarCollisionOwnershipReport"
    source_ref: ProductArtifactRef
    scene_revision: Identifier
    triangle_count: int = Field(ge=1, strict=True)
    ambiguous_triangle_count: int = Field(ge=0, strict=True)
    regions: list[LidarObjectCollisionCoverage]
    blockers: list[str] = Field(default_factory=list)


class LidarCollisionSelectionError(SceneEditRejectedError):
    """A source candidate could not be selected without incomplete ownership or QA."""


def select_lidar_collision_candidate(
    editor: SceneEditor,
    job_id: str,
    expected_scene_revision: str,
    candidate_manifest_ref: ProductArtifactRef,
) -> SceneEditResult:
    """Map exact LiDAR mesh triangles to scene objects, then commit selection through SceneEditor CAS.

    All QA and candidate receipts are re-resolved and the eligibility gate is rerun.
    Mapping is conservative: each reconstructed object must have complete, non-ambiguous
    triangle coverage before any ownership sidecar or selection record is published.
    """
    revision = editor.current(job_id)
    scene = revision.scene
    if scene.scene_revision != expected_scene_revision:
        raise SceneRevisionConflictError(
            f"scene đã đổi: client đang giữ {expected_scene_revision}, revision hiện tại là {scene.scene_revision}"
        )
    _validate_manifest_reference(candidate_manifest_ref, job_id)
    try:
        manifest_payload = editor.resolver.require(candidate_manifest_ref).read_bytes()
        manifest = LidarCollisionCandidateManifest.model_validate_json(manifest_payload)
        _validate_manifest_binding(manifest, candidate_manifest_ref, job_id)
        inputs = load_lidar_collision_eligibility_inputs(manifest, editor.resolver)
        assessment = evaluate_lidar_collision_eligibility(inputs)
    except (ArtifactStoreError, ValueError) as error:
        raise LidarCollisionSelectionError(f"Không thể xác minh candidate LiDAR: {error}") from error
    if assessment.state != "eligible" or assessment != manifest.eligibility:
        blockers = "; ".join(f"{item.code}: {item.detail}" for item in assessment.blockers)
        detail = blockers or "assessment trong manifest khác với kết quả gate được tính lại"
        raise LidarCollisionSelectionError(f"Candidate LiDAR chưa đủ điều kiện chọn: {detail}")

    try:
        build_report = LidarCollisionBuildReport.model_validate_json(
            editor.resolver.require(manifest.build_report_ref).read_bytes()
        )
        candidate_bytes = editor.resolver.require(manifest.candidate_ref).read_bytes()
    except (ArtifactStoreError, ValueError) as error:
        raise LidarCollisionSelectionError(f"Không thể xác minh mesh/report LiDAR: {error}") from error
    _validate_build_report(manifest, build_report)
    regions, report, blockers = _map_lidar_ownership(scene, manifest, candidate_bytes)
    if blockers:
        raise LidarCollisionSelectionError(
            f"Không thể chọn collision LiDAR: {', '.join(blockers)}; coverage="
            f"{report.model_dump_json(exclude={'blockers'})}"
        )

    membership_refs: dict[str, ProductArtifactRef] = {}
    for object_id, indices in regions.items():
        item = next(obj for obj in scene.objects if obj.id == object_id)
        original = item.source_collision
        if original is None:
            raise LidarCollisionSelectionError(f"{object_id}: thiếu source-bound ownership metadata")
        membership = SourceCollisionMembership(
            object_id=object_id,
            source_geometry_ref=manifest.candidate_ref,
            extraction_revision=original.extraction_revision,
            triangle_indices=indices,
        )
        payload = membership.model_dump_json(indent=2).encode("utf-8") + b"\n"
        digest = sha256_bytes(payload).removeprefix("sha256:")
        reference = ProductArtifactRef(
            artifact_type="SourceCollisionMembership",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{job_id}/collider/lidar-ownership/{digest}/membership.json",
            artifact_checksum=sha256_bytes(payload),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.COLLIDER,
            job_id=job_id,
            source_provenance={
                "algorithm": "lidar_candidate_obb_face_membership_v1",
                "source_collision_checksum": manifest.candidate_ref.artifact_checksum,
                "object_id": object_id,
            },
        )
        _publish_or_verify(editor, reference, payload)
        membership_refs[object_id] = reference

    source_qa_ref = _evidence_ref(manifest, "LidarCalibrationQAReport")
    alignment_qa_ref = _evidence_ref(manifest, "LidarCalibrationProjectionEvidence")
    selection = seal_collision_source_selection(
        mode=CollisionSourceMode.LIDAR_DERIVED,
        input_mode=manifest.input_mode,
        alignment_qa_kind=CollisionAlignmentQAKind.SENSOR_CALIBRATION_TIMING,
        source_geometry_ref=manifest.source_geometry_ref,
        source_qa_ref=source_qa_ref,
        alignment_qa_ref=alignment_qa_ref,
        profile_checksum=manifest.profile_checksum,
        config_checksum=manifest.profile_checksum,
        effective_resolution_m=build_report.voxel_m,
        output_collision_ref=manifest.candidate_ref,
    )
    selection_payload = selection.model_dump_json(indent=2).encode("utf-8") + b"\n"
    selection_digest = sha256_bytes(selection_payload).removeprefix("sha256:")
    selection_ref = ProductArtifactRef(
        artifact_type="CollisionSourceSelection",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/collider/selection/{selection_digest}/selection.json",
        artifact_checksum=sha256_bytes(selection_payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.COLLIDER,
        job_id=job_id,
        source_provenance={
            "candidate_manifest_ref": candidate_manifest_ref.model_dump(mode="json"),
            "ownership_report_checksum": sha256_bytes(canonical_json_bytes(report)),
        },
    )
    _publish_or_verify(editor, selection_ref, selection_payload)

    updated_objects = []
    for item in scene.objects:
        membership_ref = membership_refs.get(item.id)
        if membership_ref is None:
            updated_objects.append(item)
            continue
        assert item.source_collision is not None
        ownership = item.source_collision.model_copy(
            update={
                "source_geometry_ref": manifest.candidate_ref,
                "region_kind": "triangle_indices",
                "region_ref": membership_ref,
                "source_obb_dimensions_xyz_m": None,
            },
            deep=True,
        )
        updated_objects.append(item.model_copy(update={"source_collision": ownership}, deep=True))

    environment = scene.environment.model_copy(
        update={
            "collider_ref": manifest.candidate_ref,
            "collision_source_ref": manifest.candidate_ref,
            "collision_selection_ref": selection_ref,
        },
        deep=True,
    )
    updated_scene = scene.model_copy(
        update={
            "environment": environment,
            "objects": updated_objects,
            "provenance": {
                **scene.provenance,
                "collision_source_ownership": report.model_dump(mode="json"),
                "collision_source_candidate_manifest_ref": candidate_manifest_ref.model_dump(mode="json"),
            },
        },
        deep=True,
    )
    if updated_scene == scene:
        return SceneEditResult(
            job_id=job_id,
            previous_scene_revision=scene.scene_revision,
            revision=revision,
        )
    return editor.publish_next(
        job_id,
        expected_scene_revision,
        updated_scene,
        "select_lidar_collision_source",
    )


def _map_lidar_ownership(
    scene: SceneIR,
    manifest: LidarCollisionCandidateManifest,
    candidate_bytes: bytes,
) -> tuple[dict[str, list[int]], LidarCollisionOwnershipReport, list[str]]:
    try:
        mesh = trimesh.load(io.BytesIO(candidate_bytes), file_type="glb", force="mesh", process=False)
    except (ValueError, OSError) as error:
        raise LidarCollisionSelectionError(f"candidate collision mesh is invalid: {error}") from error
    triangle_count = int(len(mesh.faces)) if isinstance(mesh, trimesh.Trimesh) else 0
    if triangle_count < 1:
        raise LidarCollisionSelectionError("candidate collision mesh has no triangle faces")

    reconstructed = [
        item
        for item in scene.objects
        if item.origin == SceneObjectOrigin.RECONSTRUCTED and item.provenance.get("duplicated_from") is None
    ]
    blockers: list[str] = []
    owners: list[SourceCollisionRegion] = []
    for item in reconstructed:
        current = item.source_collision
        if current is None:
            blockers.append(f"{item.id}: missing source region")
            continue
        dimensions = current.source_obb_dimensions_xyz_m or item.primitive_dimensions_xyz_m
        if dimensions is None:
            blockers.append(f"{item.id}: missing extraction OBB dimensions")
            continue
        if (
            current.source_geometry_ref != scene.environment.geometry_ref
            and current.source_geometry_ref != scene.environment.collision_source_ref
        ):
            blockers.append(f"{item.id}: source region belongs to another geometry")
            continue
        owners.append(
            SourceCollisionRegion(
                object_id=item.id,
                source_geometry_ref=manifest.candidate_ref,
                extraction_revision=current.extraction_revision,
                source_transform=current.source_transform,
                region_kind="source_obb",
                source_obb_dimensions_xyz_m=dimensions,
            )
        )
    owner_ids = {owner.object_id for owner in owners}
    blockers.extend(
        f"{item.id}: source ownership is not a reconstructed non-duplicate object"
        for item in scene.objects
        if item.source_collision is not None and item.id not in owner_ids
    )
    if blockers:
        report = LidarCollisionOwnershipReport(
            source_ref=manifest.candidate_ref,
            scene_revision=scene.scene_revision,
            triangle_count=triangle_count,
            ambiguous_triangle_count=0,
            regions=[],
            blockers=blockers,
        )
        return {}, report, blockers

    if not owners:
        report = LidarCollisionOwnershipReport(
            source_ref=manifest.candidate_ref,
            scene_revision=scene.scene_revision,
            triangle_count=triangle_count,
            ambiguous_triangle_count=0,
            regions=[],
        )
        return {}, report, []

    mapped_objects = []
    owner_by_id = {owner.object_id: owner for owner in owners}
    for item in scene.objects:
        owner = owner_by_id.get(item.id)
        mapped_objects.append(item.model_copy(update={"source_collision": owner}, deep=True) if owner else item)
    try:
        ownership = source_triangle_ownership(
            mapped_objects,
            manifest.candidate_ref,
            candidate_bytes,
            lambda _: b"",
            obb_margin_m=0.0,
        )
    except (SourceCollisionOwnershipError, ValueError, OSError) as error:
        raise LidarCollisionSelectionError(f"candidate source ownership mapping failed: {error}") from error

    coverage_rows: list[LidarObjectCollisionCoverage] = []
    memberships: dict[str, list[int]] = {}
    for owner in owners:
        item = next(obj for obj in scene.objects if obj.id == owner.object_id)
        dimensions = owner.source_obb_dimensions_xyz_m
        assert dimensions is not None
        in_region = triangle_mask_in_box(
            ownership.centroids,
            CarveBox.from_transform(owner.source_transform, dimensions),
            margin_m=0.0,
        )
        label = next(int(key) for key, value in ownership.label_to_object_id.items() if value == owner.object_id)
        owned = ownership.owner_labels == label
        owned_count = int(np.count_nonzero(in_region & owned))
        candidate_count = int(np.count_nonzero(in_region))
        ambiguous_count = int(np.count_nonzero(in_region & (ownership.owner_labels < 0)))
        fraction = owned_count / candidate_count if candidate_count else 0.0
        coverage_rows.append(
            LidarObjectCollisionCoverage(
                object_id=item.id,
                candidate_triangle_count=candidate_count,
                owned_triangle_count=owned_count,
                ambiguous_triangle_count=ambiguous_count,
                coverage_fraction=fraction,
            )
        )
        memberships[item.id] = np.flatnonzero(owned).astype(int).tolist()
        if candidate_count == 0:
            blockers.append(f"{item.id}: no candidate triangles intersect its source region")
        elif owned_count != candidate_count:
            blockers.append(f"{item.id}: source region has {candidate_count - owned_count} ambiguous/unowned triangles")

    report = LidarCollisionOwnershipReport(
        source_ref=manifest.candidate_ref,
        scene_revision=scene.scene_revision,
        triangle_count=len(ownership.faces),
        ambiguous_triangle_count=ownership.ambiguous_triangle_count,
        regions=coverage_rows,
        blockers=blockers,
    )
    return memberships, report, blockers


def _validate_manifest_reference(reference: ProductArtifactRef, job_id: str) -> None:
    if (
        reference.artifact_type != "LidarCollisionCandidateManifest"
        or reference.producer_stage != StageId.COLLIDER
        or reference.job_id != job_id
        or not reference.artifact_uri.startswith(f"artifact://jobs/{job_id}/collider/lidar-candidate/")
    ):
        raise LidarCollisionSelectionError("candidate manifest ref has the wrong job, artifact type, or producer")


def _validate_manifest_binding(
    manifest: LidarCollisionCandidateManifest,
    reference: ProductArtifactRef,
    job_id: str,
) -> None:
    if manifest.job_id != job_id or manifest.input_mode != CollisionInputMode.LIDAR_SENSOR_PACKAGE:
        raise LidarCollisionSelectionError("candidate manifest is not a same-job sensor-package candidate")
    if (
        manifest.candidate_ref.artifact_type != "LidarCollisionCandidate"
        or manifest.candidate_ref.producer_stage != StageId.COLLIDER
        or manifest.build_report_ref.artifact_type != "LidarCollisionBuildReport"
        or manifest.build_report_ref.producer_stage != StageId.COLLIDER
        or manifest.output_collision_checksum != manifest.candidate_ref.artifact_checksum
        or reference.source_provenance != manifest.candidate_ref.source_provenance
    ):
        raise LidarCollisionSelectionError("candidate manifest refs/provenance differ from the candidate publication")


def _validate_build_report(manifest: LidarCollisionCandidateManifest, report: LidarCollisionBuildReport) -> None:
    if (
        report.output_collision_checksum != manifest.output_collision_checksum
        or report.profile_checksum != manifest.profile_checksum
        or report.profile_id != manifest.profile.profile_id
        or report.voxel_m != manifest.profile.voxel_m
        or report.source_point_checksum != manifest.source_point_checksum
        or report.self_mask_evidence_ref != manifest.self_mask_evidence_ref
        or report.self_mask_binding_checksum != manifest.self_mask_binding_checksum
    ):
        raise LidarCollisionSelectionError("candidate build report does not match its manifest/source/profile")


def _evidence_ref(manifest: LidarCollisionCandidateManifest, artifact_type: str) -> ProductArtifactRef:
    matches = [
        reference for reference in manifest.eligibility_evidence_refs if reference.artifact_type == artifact_type
    ]
    if len(matches) != 1:
        raise LidarCollisionSelectionError(f"candidate manifest requires exactly one {artifact_type}")
    return matches[0]


def _publish_or_verify(editor: SceneEditor, reference: ProductArtifactRef, payload: bytes) -> None:
    if sha256_bytes(payload) != reference.artifact_checksum:
        raise LidarCollisionSelectionError("ownership payload differs from its immutable artifact ref")
    existing = editor.resolver.locate(reference.artifact_uri, fresh=True)
    if existing is not None:
        editor.resolver.require(reference)
        editor.resolver.published(reference.artifact_uri)
        return
    try:
        published = editor.store.publish(reference, payload)
    except ArtifactAlreadyExistsError:
        editor.resolver.require(reference)
        editor.resolver.published(reference.artifact_uri)
        return
    if published != reference:
        raise LidarCollisionSelectionError("artifact writer changed LiDAR ownership identity")
