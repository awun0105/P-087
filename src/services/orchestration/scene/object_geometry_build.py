"""Build reviewed object geometry and publish it through the existing SceneIR revision fence."""

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from threading import Event

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from src.config import Settings
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.object_geometry import ObjectShellManifest
from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.models.contracts.scene import SceneObject
from src.services.orchestration.jobs.database import RuntimeTransaction
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.object_geometry_steps import SurfaceInput
from src.services.orchestration.scene.objectify import Publish, _ensure_not_cancelled, _reference
from src.services.scene.decomposition.gaussian_split import positions
from src.services.scene.editing.membership import StaleObjectMembershipRevisionError
from src.services.scene.gaussian_shell import GaussianShellError, ShellParams, build_gaussian_shell
from src.services.scene.geometry_state import object_geometry_state


class ObjectGeometryBuildError(RuntimeError):
    """A geometry build failed without changing the active scene."""

    def __init__(self, message: str, *, object_id: str | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.object_id = object_id
        self.retryable = retryable


def _build_shell(
    item: SceneObject,
    rows: np.ndarray,
    membership: ObjectMembershipArtifact,
    workspace: Path,
    publish: Publish,
) -> tuple[ProductArtifactRef, ProductArtifactRef, SurfaceInput]:
    """Build from immutable world rows using the extraction frame, never the edited pose."""
    if item.provenance.get("shell_error"):
        raise ObjectGeometryBuildError(
            f"Vỏ của {item.name} không dựng được: {item.provenance['shell_error']}. Sửa vùng vật rồi thử lại.",
            object_id=item.id,
        )
    try:
        pose = Transform.model_validate(item.provenance.get("source_transform"))
        if pose.parent_frame != "world" or pose.local_frame != item.id:
            raise ValueError("source_transform must bind world to the object frame")
    except ValueError as error:
        raise ObjectGeometryBuildError(
            f"{item.id}: source_transform không hợp lệ: {error}", object_id=item.id
        ) from error
    params = ShellParams()
    local = (positions(rows) - np.asarray(pose.translation_xyz)) @ Rotation.from_quat(
        pose.rotation_quaternion_xyzw
    ).as_matrix()
    try:
        shell = build_gaussian_shell(local, rows["opacity"], params)
    except GaussianShellError as error:
        raise ObjectGeometryBuildError(str(error), object_id=item.id) from error
    payload = trimesh.Trimesh(shell.vertices, shell.faces, process=False).export(file_type="glb")
    job_id = membership.labels_ref.job_id
    shell_ref = publish(
        _reference(job_id, "objects/shells/{digest}.glb", "ObjectShellMesh", StageId.SCENE_DECOMPOSE, payload), payload
    )
    manifest = ObjectShellManifest(
        object_id=item.id,
        shell_mesh_ref=shell_ref,
        source_membership=membership,
        source_world_from_object=pose,
        voxel_m=shell.statistics["voxel_m_effective"],
        params=asdict(params),
        statistics=shell.statistics,
        quality=shell.quality,
        vertex_count=len(shell.vertices),
        triangle_count=len(shell.faces),
        provenance={
            "surface_origin": "gaussian_shell_v1",
            "inferred_regions": "unobserved faces closed by occupancy fill",
        },
    )
    manifest_payload = manifest.model_dump_json().encode()
    manifest_ref = publish(
        _reference(
            job_id, "objects/shells/{digest}.json", "ObjectShellManifest", StageId.SCENE_DECOMPOSE, manifest_payload
        ),
        manifest_payload,
    )
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / f"{item.id}-shell.glb"
    path.write_bytes(payload)
    return (
        shell_ref,
        manifest_ref,
        SurfaceInput(item.id, path, shell_ref.artifact_checksum, workspace / f"{item.id}-collider.glb"),
    )


def build_object_geometry(
    registry: ProjectRegistry,
    settings: Settings,
    job_id: str,
    *,
    expected_revision: str,
    workspace: Path,
    object_ids: set[str] | None = None,
    commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    cancel_event: Event | None = None,
    progress: Callable[[str], None] | None = None,
) -> str:
    """Build source-bound geometry; publish one revision after all stages succeed."""
    _ensure_not_cancelled(cancel_event)
    scene = registry.scene.current(job_id).scene
    if scene.scene_revision != expected_revision:
        raise StaleObjectMembershipRevisionError(
            f"scene đã đổi: yêu cầu {expected_revision}, hiện tại {scene.scene_revision}"
        )
    if scene.environment.membership is None:
        raise ObjectGeometryBuildError("Scene không có source membership để dựng hình học.")
    if object_ids is None and object_geometry_state(scene) != "awaiting_review":
        raise ObjectGeometryBuildError("Scene phải đang duyệt tách vật trước khi tạo mesh.")
    raise ObjectGeometryBuildError("Geometry build stages are not implemented yet")
