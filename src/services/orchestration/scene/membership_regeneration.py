"""Preview immutable Gaussian rows and publish corrected ObjectGS output atomically."""

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock

import numpy as np

from src.config import Settings
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.object_membership import (
    ObjectMembershipArtifact,
    ObjectMembershipPreview,
    ObjectMembershipReassignCommand,
)
from src.models.contracts.scene import SceneIR
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.orchestration.jobs.database import RuntimeTransaction
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.objectify import (
    CorrectedMembership,
    _ensure_not_cancelled,
    _reference,
    objectify_with_retry,
)
from src.services.scene.decomposition.gaussian_split import positions, read_gaussian_ply
from src.services.scene.editing.membership import (
    ObjectMembershipValidationError,
    decode_gaussian_membership_labels,
    encode_gaussian_membership_labels,
    select_source_gaussians,
    validate_object_membership_command,
)
from src.services.scene.floor_model import above_floor_mask, fit_canonical_floor_model, point_cloud_checksum


@dataclass(frozen=True)
class MembershipSource:
    positions: np.ndarray
    rows: np.ndarray
    labels: np.ndarray
    manifest: ObjectMembershipArtifact
    floor_protected: np.ndarray | None


def _load_membership_source(
    resolver: ArtifactResolver, membership: ObjectMembershipArtifact, *, protect_floor: bool
) -> MembershipSource:
    payload = resolver.require(membership.source_visual_ref).read_bytes()
    if "sha256:" + hashlib.sha256(payload).hexdigest() != membership.source_visual_ref.artifact_checksum:
        raise ObjectMembershipValidationError("source PLY checksum mismatch")
    rows = read_gaussian_ply(payload)
    xyz = positions(rows)
    labels = decode_gaussian_membership_labels(resolver.require(membership.labels_ref).read_bytes(), membership)
    protected = None
    if protect_floor:
        floor = fit_canonical_floor_model(xyz, point_cloud_checksum(xyz))
        protected = ~above_floor_mask(xyz, floor)
    return MembershipSource(xyz, rows, labels, membership, protected)


_SOURCE_CACHE: OrderedDict[tuple[str, str, str], tuple[np.ndarray, np.ndarray, np.ndarray]] = OrderedDict()
_SOURCE_LOCK = Lock()


def load_membership_source(registry: ProjectRegistry, job_id: str, scene: SceneIR) -> MembershipSource:
    """Cache immutable world rows/floor only; always decode a fresh current label array."""
    membership = scene.environment.membership
    if membership is None:
        raise ObjectMembershipValidationError("scene has no persisted Gaussian membership")
    key = (job_id, membership.labels_ref.artifact_checksum, membership.source_visual_ref.artifact_checksum)
    with _SOURCE_LOCK:
        cached = _SOURCE_CACHE.get(key)
        if cached is None:
            source = _load_membership_source(registry.runtime_resolver, membership, protect_floor=True)
            cached = source.positions, source.rows, source.floor_protected
            for array in cached:
                array.setflags(write=False)
            _SOURCE_CACHE[key] = cached
            if len(_SOURCE_CACHE) > 2:
                _SOURCE_CACHE.popitem(last=False)
        _SOURCE_CACHE.move_to_end(key)
    labels = decode_gaussian_membership_labels(
        registry.runtime_resolver.require(membership.labels_ref).read_bytes(), membership
    )
    return MembershipSource(cached[0], cached[1], labels, membership, cached[2])


def prepare_correction(
    editor: SceneEditor, job_id: str, command: ObjectMembershipReassignCommand
) -> tuple[SceneIR, ObjectMembershipArtifact, np.ndarray, dict[str, object]]:
    scene = editor.current(job_id).scene
    membership = validate_object_membership_command(scene, command)
    source = _load_membership_source(editor.resolver, membership, protect_floor=command.source_object_id is None)
    xyz, labels, protected = source.positions, source.labels, source.floor_protected
    selected, preview = select_source_gaussians(
        xyz,
        labels,
        membership,
        command,
        protected=protected,
    )
    updated = labels.copy()
    target_labels = [
        int(key) for key, owner in membership.label_to_object_id.items() if owner == command.target_object_id
    ]
    updated[selected] = min(target_labels) if target_labels else -1
    preview["remaining_gaussians"] = {
        owner: int(
            np.isin(updated, [int(key) for key, bound in membership.label_to_object_id.items() if bound == owner]).sum()
        )
        for owner in preview["affected_object_ids"]
    }
    return scene, membership, updated, preview


def preview_correction(
    editor: SceneEditor, job_id: str, command: ObjectMembershipReassignCommand
) -> ObjectMembershipPreview:
    """Read-only; Apply must submit the identical revision/checksum-bound command."""
    return ObjectMembershipPreview.model_validate(prepare_correction(editor, job_id, command)[3])


def regenerate_membership(
    registry: ProjectRegistry,
    job_id: str,
    settings: Settings,
    workspace: Path,
    *,
    command: ObjectMembershipReassignCommand,
    actor_id: str,
    expected_revision: str,
    commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    cancel_event: Event | None = None,
    progress: Callable[[str], None] | None = None,
) -> str:
    _ensure_not_cancelled(cancel_event)
    if command.expected_scene_revision != expected_revision:
        raise ObjectMembershipValidationError("correction command and queue base revision differ")
    scene, membership, labels, preview = prepare_correction(registry.scene, job_id, command)
    if scene.environment.object_aware_collision_ref is None:
        raise ObjectMembershipValidationError(
            "queued regeneration requires an ObjectGS scene; use legacy ROI correction"
        )
    if scene.environment.collision_selection_ref is not None:
        raise ObjectMembershipValidationError("correct the source scene before selecting another collision source")
    if any(count < 50 for count in preview["remaining_gaussians"].values()):
        raise ObjectMembershipValidationError(
            "correction must retain at least 50 Gaussians per object; use Delete for removal"
        )
    job = registry.get_job(job_id)
    bundle = job_bundle(registry, job)
    if bundle is None or bundle.canonical_geometry_ref != membership.source_geometry_ref:
        raise ObjectMembershipValidationError("correction reconstruction source geometry mismatch")
    store = FilesystemArtifactStore(registry.runtime_resolver)

    def publish(reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        if registry.runtime_resolver.locate(reference.artifact_uri) is not None:
            if registry.runtime_resolver.require(reference).read_bytes() != payload:
                raise ObjectMembershipValidationError("immutable correction artifact bytes differ")
            registry.runtime_resolver.published(reference.artifact_uri)
            return reference
        return store.publish(reference, payload)

    mapping = {}
    for owner in sorted(set(membership.label_to_object_id.values())):
        owner_labels = [int(key) for key, value in membership.label_to_object_id.items() if value == owner]
        label = min(owner_labels)
        labels[np.isin(labels, owner_labels)] = label
        mapping[str(label)] = owner
    mapping = dict(sorted(mapping.items(), key=lambda pair: int(pair[0])))
    payload = encode_gaussian_membership_labels(
        labels, gaussian_count=membership.gaussian_count, label_to_object_id=mapping
    )
    labels_ref = publish(
        _reference(
            job_id, "objects/membership/{digest}.i32le", "ObjectMembershipLabels", StageId.SCENE_DECOMPOSE, payload
        ),
        payload,
    )
    corrected = membership.model_copy(update={"labels_ref": labels_ref, "label_to_object_id": mapping}, deep=True)
    originals = {item.id: item for item in scene.objects}
    poses = {
        owner: originals[owner].source_collision.source_transform
        for owner in set(membership.label_to_object_id.values())
    }
    correction_payload = json.dumps(
        {
            "operation": "reassign",
            "actor_id": actor_id,
            "command": command.model_dump(mode="json"),
            "preview": preview,
            "source_membership": membership.model_dump(mode="json"),
            "corrected_membership": corrected.model_dump(mode="json"),
        },
        sort_keys=True,
    ).encode()
    correction_ref = publish(
        _reference(
            job_id,
            "objects/corrections/{digest}.json",
            "ObjectMembershipCorrection",
            StageId.SCENE_DECOMPOSE,
            correction_payload,
        ),
        correction_payload,
    )
    # The existing producer trains a shared labelled model. Regenerate that model
    # rather than claiming its old checkpoint reflects changed supervision.
    result = objectify_with_retry(
        registry,
        job,
        bundle,
        settings,
        workspace,
        publish,
        extraction_revision=membership.extraction_revision,
        geometry_method="objectgs",
        correction=CorrectedMembership(corrected, labels, poses, correction_ref),
        cancel_event=cancel_event,
        progress=progress,
    )
    if result.environment.membership != corrected:
        raise ObjectMembershipValidationError("regenerated membership receipt mismatch")
    generated = {item.id: item for item in result.objects}
    if set(generated) != set(poses):
        raise ObjectMembershipValidationError("regeneration changed source object identity")
    objects = []
    for item in scene.objects:
        if item.id not in generated:
            objects.append(item)
            continue
        fresh = generated[item.id]
        objects.append(
            item.model_copy(
                update={
                    "visual_ref": fresh.visual_ref,
                    "geometry_ref": fresh.geometry_ref,
                    "surface_mesh_ref": fresh.surface_mesh_ref,
                    "collider": fresh.collider,
                    "primitive_dimensions_xyz_m": fresh.primitive_dimensions_xyz_m,
                    "provenance": {
                        **item.provenance,
                        **fresh.provenance,
                        "membership_regeneration": {
                            "input_scene_revision": expected_revision,
                            "actor_id": actor_id,
                            "source_membership_checksum": labels_ref.artifact_checksum,
                        },
                    },
                },
                deep=True,
            )
        )
    environment = scene.environment.model_copy(
        update={
            key: getattr(result.environment, key)
            for key in ("visual_ref", "visual_master_ref", "membership", "collider_ref", "object_aware_collision_ref")
        },
        deep=True,
    )
    updated = scene.model_copy(
        update={
            "objects": objects,
            "environment": environment,
            "provenance": {
                **scene.provenance,
                **result.provenance,
                "membership_correction": {
                    "operation": "reassign",
                    "evidence_ref": correction_ref.model_dump(mode="json"),
                    "actor_id": actor_id,
                    "preview": {key: value for key, value in preview.items() if key != "source_gaussian_indices"},
                },
            },
        },
        deep=True,
    )
    _ensure_not_cancelled(cancel_event)
    if progress:
        progress("publishing")
    published = registry.scene.publish_next(
        job_id, expected_revision, updated, "object_membership_regeneration", commit_guard=commit_guard
    )
    return published.revision.scene.scene_revision
