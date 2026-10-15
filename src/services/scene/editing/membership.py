"""Validation and safe serialization for source-Gaussian ownership maps."""

from __future__ import annotations

import hashlib
from typing import TypeAlias

import numpy as np

from src.models.contracts.object_membership import (
    ObjectMembershipArtifact,
    ObjectMembershipMergeCommand,
    ObjectMembershipReassignCommand,
)
from src.models.contracts.scene import SceneIR, SceneObjectOrigin, SceneObjectState

MembershipCommand: TypeAlias = ObjectMembershipMergeCommand | ObjectMembershipReassignCommand
_BACKGROUND_LABEL = -1


def _int32_labels(labels: np.ndarray, *, gaussian_count: int | None = None) -> np.ndarray:
    if (
        labels.ndim != 1
        or not np.issubdtype(labels.dtype, np.integer)
        or (gaussian_count is not None and len(labels) != gaussian_count)
    ):
        raise ObjectMembershipValidationError("membership labels must be one integer per source Gaussian row")
    bounds = np.iinfo(np.int32)
    if labels.size and (int(labels.min()) < bounds.min or int(labels.max()) > bounds.max):
        raise ObjectMembershipValidationError("membership label exceeds signed int32 range")
    return labels.astype(np.int32, copy=False)


def membership_labels_for_parts(labels: np.ndarray, part_labels: list[int]) -> np.ndarray:
    """Keep only rows emitted as parts by `split`; discarded small labels remain background."""
    values = _int32_labels(labels)
    part_values = np.asarray(part_labels)
    retained = _int32_labels(part_values) if part_values.size else np.empty(0, dtype=np.int32)
    if retained.ndim != 1 or len(np.unique(retained)) != len(retained) or np.any(retained < 0):
        raise ObjectMembershipValidationError("split part labels must be unique non-negative integers")
    result = np.full(len(values), _BACKGROUND_LABEL, dtype=np.int32)
    if retained.size:
        selected = np.isin(values, retained)
        result[selected] = values[selected]
    return result


class ObjectMembershipValidationError(ValueError):
    """A membership payload or correction request is not safe to apply."""


class StaleObjectMembershipRevisionError(ObjectMembershipValidationError):
    """The correction command targets a SceneIR revision that is no longer current."""


def encode_gaussian_membership_labels(
    labels: np.ndarray,
    *,
    gaussian_count: int,
    label_to_object_id: dict[str, str],
) -> bytes:
    """Serialize one exclusive int32 label per source PLY row; `-1` is background."""
    values = _int32_labels(labels, gaussian_count=gaussian_count)
    allowed = {_BACKGROUND_LABEL, *(int(label) for label in label_to_object_id)}
    if any(int(label) not in allowed for label in np.unique(values)):
        raise ObjectMembershipValidationError("membership labels contain an unmapped object owner")
    return values.astype("<i4", copy=False).tobytes(order="C")


def decode_gaussian_membership_labels(payload: bytes, manifest: ObjectMembershipArtifact) -> np.ndarray:
    """Verify label bytes against the manifest checksum, row count, encoding, and owner map."""
    expected_checksum = "sha256:" + hashlib.sha256(payload).hexdigest()
    if expected_checksum != manifest.labels_ref.artifact_checksum:
        raise ObjectMembershipValidationError("membership label bytes do not match labels_ref checksum")
    if len(payload) != manifest.gaussian_count * np.dtype("<i4").itemsize:
        raise ObjectMembershipValidationError("membership label byte count does not match gaussian_count")
    labels = np.frombuffer(payload, dtype="<i4").copy()
    allowed = {_BACKGROUND_LABEL, *(int(label) for label in manifest.label_to_object_id)}
    if any(int(label) not in allowed for label in np.unique(labels)):
        raise ObjectMembershipValidationError("membership label array contains an unmapped object owner")
    return labels


def validate_object_membership_command(scene: SceneIR, command: MembershipCommand) -> ObjectMembershipArtifact:
    """Fail closed unless the checksummed membership belongs to eligible current candidates."""
    if scene.scene_revision != command.expected_scene_revision:
        raise StaleObjectMembershipRevisionError(
            f"membership command targets {command.expected_scene_revision}; current SceneIR is {scene.scene_revision}"
        )
    manifest = scene.environment.membership
    if manifest is None:
        raise ObjectMembershipValidationError("scene has no persisted Gaussian membership; correction is unavailable")
    if manifest.labels_ref.artifact_checksum != command.membership_checksum:
        raise ObjectMembershipValidationError("membership checksum does not match the current SceneIR")
    if manifest.source_geometry_ref != scene.environment.geometry_ref:
        raise ObjectMembershipValidationError("membership source geometry does not match the current SceneIR")
    mapped_ids = set(manifest.label_to_object_id.values())
    scene_objects = {item.id: item for item in scene.objects}
    if not mapped_ids <= scene_objects.keys():
        raise ObjectMembershipValidationError("membership map references objects missing from the current SceneIR")

    if isinstance(command, ObjectMembershipMergeCommand):
        selected_ids = {command.primary_object_id, *command.secondary_object_ids}
    else:
        selected_ids = {object_id for object_id in (command.source_object_id, command.target_object_id) if object_id}
    if not selected_ids <= mapped_ids:
        raise ObjectMembershipValidationError("correction command must target objects in the current membership map")

    if isinstance(command, ObjectMembershipMergeCommand):
        semantic_classes = {scene_objects[object_id].semantic_class for object_id in selected_ids}
        if len(semantic_classes) > 1 and command.semantic_class_source_object_id is None:
            raise ObjectMembershipValidationError(
                "merged candidates have conflicting semantic classes; choose semantic_class_source_object_id"
            )

    for object_id in selected_ids:
        item = scene_objects[object_id]
        ownership = item.source_collision
        if (
            (
                item.state != SceneObjectState.CANDIDATE
                and not (
                    scene.environment.object_aware_collision_ref is not None
                    and item.state == SceneObjectState.CONFIRMED
                )
            )
            or item.provenance.get("review") in {"IGNORED", "DELETED", "MERGED"}
            or item.origin != SceneObjectOrigin.RECONSTRUCTED
            or item.asset_ref is not None
            or ownership is None
            or ownership.source_geometry_ref != scene.environment.geometry_ref
            or ownership.extraction_revision != manifest.extraction_revision
            or (scene.environment.object_aware_collision_ref is None and ownership.source_transform != item.transform)
        ):
            raise ObjectMembershipValidationError(
                f"object {object_id} is confirmed, moved, asset-backed, or lacks matching source ownership"
            )
    return manifest


def select_source_gaussians(
    positions: np.ndarray,
    labels: np.ndarray,
    manifest: ObjectMembershipArtifact,
    command: ObjectMembershipReassignCommand,
    *,
    protected: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, object]]:
    """Resolve an immutable source-row selection; current object poses are never inputs."""
    if positions.shape != (manifest.gaussian_count, 3) or not np.isfinite(positions).all():
        raise ObjectMembershipValidationError("source Gaussian positions do not match membership")
    _int32_labels(labels, gaussian_count=manifest.gaussian_count)
    if command.source_gaussian_indices is not None:
        if command.source_visual_checksum != manifest.source_visual_ref.artifact_checksum:
            raise ObjectMembershipValidationError("source Gaussian selection checksum mismatch")
        if command.source_gaussian_indices[-1] >= len(labels):
            raise ObjectMembershipValidationError("source Gaussian index is outside source PLY")
        selected = np.zeros(len(labels), dtype=bool)
        selected[command.source_gaussian_indices] = True
    else:
        assert command.region is not None
        selected = np.all(
            (positions >= np.asarray(command.region.min_xyz_m) - 1e-6)
            & (positions <= np.asarray(command.region.max_xyz_m) + 1e-6),
            axis=1,
        )
    source_labels = [
        int(label) for label, owner in manifest.label_to_object_id.items() if owner == command.source_object_id
    ]
    owned = labels == -1 if command.source_object_id is None else np.isin(labels, source_labels)
    wrong_owner = int(np.count_nonzero(selected & ~owned))
    selected &= owned
    protected_count = 0
    if protected is not None and command.target_object_id is not None:
        protected_count = int(np.count_nonzero(selected & protected))
        selected &= ~protected
    indices = np.flatnonzero(selected)
    if not len(indices):
        raise ObjectMembershipValidationError("selection contains no transferable source Gaussian rows")
    return selected, {
        "scene_revision": command.expected_scene_revision,
        "membership_checksum": command.membership_checksum,
        "source_visual_checksum": manifest.source_visual_ref.artifact_checksum,
        "source_object_id": command.source_object_id,
        "target_object_id": command.target_object_id,
        "affected_object_ids": list(
            dict.fromkeys(owner for owner in (command.source_object_id, command.target_object_id) if owner)
        ),
        "gaussian_count": len(indices),
        "wrong_owner_count": wrong_owner,
        "protected_count": protected_count,
        "source_gaussian_indices": indices.tolist(),
    }
