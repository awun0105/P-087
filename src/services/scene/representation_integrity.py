"""Verify SOURCE rows against sealed membership without changing ownership or source assets."""

from collections.abc import Callable
from pathlib import Path

import numpy as np

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.scene import SceneIR
from src.services.orchestration.artifacts.checksum import verify_file_checksum
from src.services.orchestration.artifacts.errors import ArtifactStoreError
from src.services.scene.decomposition.gaussian_split import positions, read_gaussian_ply
from src.services.scene.editing.membership import decode_gaussian_membership_labels
from src.services.scene.representation_composition import scene_representations


def representation_issues(
    scene: SceneIR, resolve: Callable[[ProductArtifactRef], Path] | None
) -> list[tuple[str, str]]:
    """Return deterministic (object ID, blocker); missing evidence is never current-pose fallback."""
    dispositions = scene_representations(scene)
    issues = [(item.object_id, code) for item in dispositions for code in item.readiness_blockers]
    required = [item for item in dispositions if item.source_visual_required]
    if not required:
        return issues
    if resolve is None:
        return issues + [(item.object_id, "SOURCE_ARTIFACT_RESOLVER_MISSING") for item in required]

    def read(ref: ProductArtifactRef) -> bytes:
        path = resolve(ref)
        verify_file_checksum(path, ref.artifact_checksum)
        return path.read_bytes()

    membership = scene.environment.membership
    if membership is None:
        return issues + [(item.object_id, "SOURCE_MEMBERSHIP_MISSING") for item in required]
    try:
        if (
            membership.source_geometry_ref != scene.environment.geometry_ref
            or membership.coordinate_system != scene.coordinate_system
        ):
            raise ValueError("membership source geometry changed")
        if not set(membership.label_to_object_id.values()) <= {item.id for item in scene.objects}:
            raise ValueError("membership references absent objects")
        labels = decode_gaussian_membership_labels(read(membership.labels_ref), membership)
        master = read_gaussian_ply(read(membership.source_visual_ref))
        if len(master) != membership.gaussian_count:
            raise ValueError("source row count differs from membership")
    except (ArtifactStoreError, OSError, ValueError, TypeError, KeyError, StopIteration):
        return issues + [(item.object_id, "SOURCE_MEMBERSHIP_INVALID") for item in required]
    objects = {item.id: item for item in scene.objects}
    for disposition in required:
        item = objects[disposition.object_id]
        owned_labels = [int(key) for key, owner in membership.label_to_object_id.items() if owner == item.id]
        source = master[np.isin(labels, owned_labels)]
        if not len(source) and item.provenance.get("membership_reassign_blocker") == "NO_SOURCE_GAUSSIANS":
            continue
        if item.visual_ref is None:
            issues.append((item.id, "SOURCE_VISUAL_MISSING"))
            continue
        if disposition.source_transform is None:
            continue  # Missing ref/pose already has an explicit policy blocker.
        try:
            rows = read_gaussian_ply(read(item.visual_ref))
            fields = {
                "x",
                "y",
                "z",
                "opacity",
                *(f"scale_{i}" for i in range(3)),
                *(f"rot_{i}" for i in range(4)),
                *(f"f_dc_{i}" for i in range(3)),
            }
            if not fields <= set(rows.dtype.names or ()):
                raise ValueError("Gaussian layout is unsupported")
            if any(not np.isfinite(rows[field]).all() for field in rows.dtype.names or ()):
                raise ValueError("Gaussian attributes are nonfinite")
            if not len(source) or rows.dtype != source.dtype or len(rows) != len(source):
                raise ValueError("object source membership row layout/count mismatch")
            world = positions(rows) + np.asarray(disposition.source_transform.translation_xyz)
            if not np.allclose(world, positions(source), rtol=0, atol=1e-5):
                raise ValueError("object local rows do not reconstruct their immutable source positions")
            for field in source.dtype.names or ():
                if field not in {"x", "y", "z"} and not np.array_equal(rows[field], source[field]):
                    raise ValueError("Gaussian attribute differs from immutable source")
        except (ArtifactStoreError, OSError, ValueError, TypeError, KeyError, StopIteration):
            issues.append((item.id, "SOURCE_VISUAL_INVALID"))
    return issues
