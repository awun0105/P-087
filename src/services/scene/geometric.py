"""Tách vật thể ứng viên bằng hình học từ collision mesh canonical (EX-SCENE baseline thật).

Khi chưa có SAM2 runtime, đây là đường chạy được trên bundle thật: voxel hoá đỉnh của
collision mesh REC-05 (mét, Z-up, sàn z=0), bỏ phần sàn, tách khối liên thông 26-lân cận
(ý tưởng clustering + OBB theo R2G `get_aabb.py`/SAMPro3D DBSCAN, playbook: Tier-0 donor cho
SCENE-03/06). Khối cỡ vật thể (pallet, thùng) → SceneObject CANDIDATE có hộp OBB theo yaw;
khối lớn (kệ, tường) để lại cho môi trường. Người dùng xác nhận ứng viên (SCENE-05).

Ngưỡng là heuristic baseline, ghi trong provenance; không claim chất lượng segmentation.
"""

import hashlib
import io
import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import trimesh
from scipy import ndimage

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.scene import SceneObject, SceneObjectOrigin, SceneObjectState

METHOD = "geometric_voxel_components_v1"


@dataclass(frozen=True)
class GeometricConfig:
    """Ngưỡng baseline (mét)."""

    voxel_m: float = 0.10
    floor_clearance_m: float = 0.06
    max_height_m: float = 2.4
    min_footprint_m: float = 0.25
    max_footprint_m: float = 2.5
    min_height_m: float = 0.15
    max_object_height_m: float = 2.2
    min_voxels: int = 8
    max_candidates: int = 30


@dataclass(frozen=True)
class Candidate:
    """Một khối cỡ vật thể: tâm, yaw và kích thước hộp (mét)."""

    center: tuple[float, float, float]
    yaw: float
    dimensions: tuple[float, float, float]
    voxels: int


def _yaw_box(points: np.ndarray) -> tuple[tuple[float, float, float], float, tuple[float, float, float]]:
    """OBB quanh trục Z: PCA trên mặt phẳng XY, chiều cao từ min..max z."""
    xy = points[:, :2]
    mean = xy.mean(axis=0)
    if len(points) >= 3:
        _, _, vt = np.linalg.svd(xy - mean, full_matrices=False)
        axis = vt[0]
    else:
        axis = np.array([1.0, 0.0])
    yaw = math.atan2(axis[1], axis[0])
    rotation = np.array([[math.cos(yaw), math.sin(yaw)], [-math.sin(yaw), math.cos(yaw)]])
    local = (xy - mean) @ rotation.T
    low, high = local.min(axis=0), local.max(axis=0)
    mid_local = (low + high) / 2
    center_xy = mean + mid_local @ rotation
    z_low, z_high = points[:, 2].min(), points[:, 2].max()
    dims = (float(high[0] - low[0]), float(high[1] - low[1]), float(z_high - z_low))
    return (float(center_xy[0]), float(center_xy[1]), float((z_low + z_high) / 2)), yaw, dims


def find_candidates(vertices: np.ndarray, config: GeometricConfig = GeometricConfig()) -> list[Candidate]:
    """Khối liên thông của voxel phía trên sàn, lọc theo cỡ vật thể, lớn trước."""
    above = vertices[(vertices[:, 2] > config.floor_clearance_m) & (vertices[:, 2] < config.max_height_m)]
    if not len(above):
        return []
    cells = np.floor(above / config.voxel_m).astype(np.int64)
    origin = cells.min(axis=0)
    shape = cells.max(axis=0) - origin + 1
    grid = np.zeros(shape, dtype=bool)
    grid[tuple((cells - origin).T)] = True
    labels, count = ndimage.label(grid, structure=np.ones((3, 3, 3), dtype=bool))
    found: list[Candidate] = []
    for index, box in enumerate(ndimage.find_objects(labels), start=1):
        if box is None:
            continue
        local = np.argwhere(labels[box] == index)
        if len(local) < config.min_voxels:
            continue
        corner = np.array([s.start for s in box])
        centers = (local + corner + origin + 0.5) * config.voxel_m
        center, yaw, dims = _yaw_box(centers)
        dims = tuple(max(value + config.voxel_m, config.voxel_m) for value in dims)  # bề dày một voxel
        footprint = max(dims[0], dims[1])
        if not (config.min_footprint_m <= footprint <= config.max_footprint_m):
            continue
        if not (config.min_height_m <= dims[2] <= config.max_object_height_m):
            continue
        found.append(Candidate(center, yaw, dims, len(local)))  # type: ignore[arg-type]
    found.sort(key=lambda item: item.dimensions[0] * item.dimensions[1] * item.dimensions[2], reverse=True)
    return found[: config.max_candidates]


def _yaw_quaternion(yaw: float) -> tuple[float, float, float, float]:
    return (0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2))


def _box_glb(dimensions: tuple[float, float, float]) -> bytes:
    """Mesh hộp trong khung local của vật thể (tâm ở gốc) để làm geometry_ref."""
    buffer = io.BytesIO()
    trimesh.creation.box(extents=dimensions).export(buffer, file_type="glb")
    return buffer.getvalue()


def box_from_points(points: np.ndarray, voxels: int | None = None) -> Candidate:
    """Hộp OBB quanh trục Z (đứng trên sàn) cho một cụm điểm — thay OBB tối thiểu Open3D của R2G."""
    center, yaw, dims = _yaw_box(points)
    return Candidate(center, yaw, tuple(max(value, 0.05) for value in dims), voxels or len(points))  # type: ignore[arg-type]


def objects_from_candidates(
    job_id: str,
    candidates: list[Candidate],
    publish: Callable[[ProductArtifactRef, bytes], ProductArtifactRef],
    provenance: dict,
) -> list[SceneObject]:
    """SceneObject CANDIDATE (chưa active) cho từng hộp; GLB hộp publish bất biến theo nội dung."""
    objects: list[SceneObject] = []
    for number, candidate in enumerate(candidates, start=1):
        object_id = f"candidate-{number:03d}"
        payload = _box_glb(candidate.dimensions)
        digest = hashlib.sha256(payload).hexdigest()
        reference = publish(
            ProductArtifactRef(
                artifact_type="SceneObjectGeometry",
                schema_version="1.0",
                artifact_uri=f"artifact://jobs/{job_id}/scene/candidates/{digest}.glb",
                artifact_checksum=f"sha256:{digest}",
                data_class=ArtifactDataClass.DERIVED,
                producer_stage=StageId.OBJECT_ASSOC,
                job_id=job_id,
            ),
            payload,
        )
        objects.append(
            SceneObject(
                id=object_id,
                name=f"Vật thể {number}",
                state=SceneObjectState.CANDIDATE,
                origin=SceneObjectOrigin.RECONSTRUCTED,
                active=False,
                local_frame=object_id,
                transform=Transform(
                    parent_frame="world",
                    local_frame=object_id,
                    translation_xyz=candidate.center,
                    rotation_quaternion_xyzw=_yaw_quaternion(candidate.yaw),
                ),
                geometry_ref=reference,
                primitive_dimensions_xyz_m=candidate.dimensions,
                tags=[provenance.get("method", METHOD)],
                provenance={**provenance, "support": candidate.voxels, "note": "ứng viên, cần người xác nhận"},
            )
        )
    return objects


def candidate_objects(
    job_id: str,
    vertices: np.ndarray,
    publish: Callable[[ProductArtifactRef, bytes], ProductArtifactRef],
    config: GeometricConfig = GeometricConfig(),
) -> list[SceneObject]:
    """Fallback hình học: ứng viên từ collision mesh (ADR 0006 §2)."""
    return objects_from_candidates(
        job_id, find_candidates(vertices, config), publish, {"method": METHOD, "voxel_m": config.voxel_m}
    )


def collision_vertices(glb_bytes: bytes) -> np.ndarray:
    """Đỉnh của collision GLB canonical (mét, Z-up) — mesh do REC-05 publish."""
    mesh = trimesh.load(io.BytesIO(glb_bytes), file_type="glb", force="mesh")
    return np.asarray(mesh.vertices, dtype=float)
