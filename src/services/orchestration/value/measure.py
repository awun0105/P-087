"""Máy đo P2/P3 (architecture §15.3 quy tắc 3–4): tính sai số đoạn đo, bề rộng khe và nhất quán sau khi dời.

Các hàm đo là thuần tính toán: cùng đầu vào cho cùng kết quả, không ghi gì và không đọc ground truth.
Toạ độ theo khung canonical của scene (mét, Z-up, sàn z = 0).
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import trimesh
from pydantic import BaseModel
from scipy.spatial.transform import Rotation

from src.models.contracts.scene import ColliderSpec, ColliderType, SceneIR, SceneObject
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.effective_collision import _job_simulation_config, effective_environment
from src.services.orchestration.scene.errors import SceneError
from src.services.orchestration.value.ground_truth import GapCheck, MeasuredDistance, RobotProfile
from src.services.scene.representation_composition import resolve_representation
from src.services.simulation.mesh_geometry import load_mesh_parts

#: Bước quét độ cao của khe (quy tắc 3: z = h_min, h_min + 0.05, … ≤ h_max).
HEIGHT_STEP_M = 0.05
#: Tia cắt ra khỏi mặt phẳng của đoạn hai điểm sai số dưới ngưỡng này (m) thì coi như trùng điểm.
_RAY_EPSILON = 1e-9


class DistanceResult(BaseModel):
    distance_id: str
    sim_m: float
    real_m: float
    error_m: float
    error_pct: float


class GapResult(BaseModel):
    gap_id: str
    sim_width_m: float
    sim_passable: bool
    real_passable: bool
    agree: bool
    kind: Literal["ok", "missed_obstacle", "false_obstacle"]
    heights_checked: int


@dataclass(frozen=True)
class CollisionWorld:
    """Collision tổng hợp của một revision: môi trường hiệu lực cộng collider của từng vật đang xuất."""

    #: Lưới canonical đã gộp mọi thành phần.
    mesh: trimesh.Trimesh
    #: Id vật sở hữu từng tam giác; chuỗi rỗng là môi trường.
    face_owner: np.ndarray
    #: Vật có mọi thành phần collider kín.
    solid_owners: frozenset[str]
    #: Chỉ số mảnh collider của từng tam giác (−1 là môi trường). Collider CoACD gồm nhiều mảnh lồi có thể chồng nhau.
    face_part: np.ndarray
    #: Các mảnh kín: kiểm "điểm ở trong vật" theo từng mảnh, vì chẵn lẻ trên cả vật sai ở vùng hai mảnh chồng nhau.
    solid_parts: frozenset[int]


def distance_error(d: MeasuredDistance) -> DistanceResult:
    """Sai số của một đoạn đo: |b−a| của mô phỏng so với số thước."""
    sim = math.dist(d.a, d.b)
    error = sim - d.real_m
    return DistanceResult(
        distance_id=d.id,
        sim_m=sim,
        real_m=d.real_m,
        error_m=error,
        error_pct=abs(error) / d.real_m * 100.0,
    )


def _heights(robot: RobotProfile) -> list[float]:
    count = math.floor((robot.height_max_m - robot.height_min_m) / HEIGHT_STEP_M + 1e-9) + 1
    return [robot.height_min_m + index * HEIGHT_STEP_M for index in range(count)]


def _ray_hits(triangles: np.ndarray, origin: np.ndarray, direction: np.ndarray) -> np.ndarray:
    """Khoảng cách t > 0 của mọi giao điểm tia với tam giác (Möller–Trumbore, numpy thuần, không cần rtree)."""
    if len(triangles) == 0:
        return np.empty(0)
    v0, v1, v2 = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    edge1 = v1 - v0
    edge2 = v2 - v0
    p = np.cross(direction, edge2)
    det = np.einsum("ij,ij->i", edge1, p)
    parallel = np.abs(det) <= 1e-12
    inv = np.where(parallel, 0.0, 1.0 / np.where(parallel, 1.0, det))
    s = origin - v0
    u = np.einsum("ij,ij->i", s, p) * inv
    q = np.cross(s, edge1)
    v = (q @ direction) * inv
    t = np.einsum("ij,ij->i", edge2, q) * inv
    hit = ~parallel & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > _RAY_EPSILON)
    return t[hit]


def _first_hit(triangles: np.ndarray, origin: np.ndarray, direction: np.ndarray) -> float:
    hits = _ray_hits(triangles, origin, direction)
    return float(hits.min()) if len(hits) else math.inf


def _inside_solid(world: CollisionWorld, origin: np.ndarray, direction: np.ndarray) -> bool:
    """Điểm nằm trong vật khi tia đi ra cắt số lẻ mặt của **một mảnh** kín nào đó của vật.

    Kiểm theo mảnh, không theo cả vật: điểm trong vùng chồng của hai mảnh lồi cắt 2 + 2 mặt, chẵn lẻ trên cả vật sẽ báo sai là ngoài.
    """
    faces = world.mesh.triangles
    for part in world.solid_parts:
        owned = faces[world.face_part == part]
        if len(_ray_hits(owned, origin, direction)) % 2 == 1:
            return True
    return False


def gap_width(world: CollisionWorld, gap: GapCheck, robot: RobotProfile) -> GapResult:
    """Bề rộng mô phỏng của khe: nhỏ nhất theo độ cao, mỗi phía bị chặn ở |b−a|/2."""
    a = np.asarray(gap.a, dtype=float)
    b = np.asarray(gap.b, dtype=float)
    half = float(np.linalg.norm(b - a)) / 2.0
    horizontal = np.array([b[0] - a[0], b[1] - a[1], 0.0])
    norm = float(np.linalg.norm(horizontal))
    if norm <= _RAY_EPSILON:
        raise ValueError(f"khe kiểm {gap.id}: đoạn nằm dọc, không có hướng ngang để đo bề rộng")
    direction = horizontal / norm
    middle = (a + b) / 2.0
    triangles = world.mesh.triangles
    z_low = triangles[:, :, 2].min(axis=1)
    z_high = triangles[:, :, 2].max(axis=1)
    heights = _heights(robot)
    widths: list[float] = []
    for z in heights:
        origin = np.array([middle[0], middle[1], z])
        if _inside_solid(world, origin, direction):
            widths.append(0.0)
            continue
        candidates = triangles[(z_low <= z) & (z_high >= z)]
        right = min(_first_hit(candidates, origin, direction), half)
        left = min(_first_hit(candidates, origin, -direction), half)
        widths.append(left + right)
    sim_width = min(widths)
    sim_passable = sim_width >= robot.width_m + 2.0 * robot.safety_margin_m
    agree = sim_passable == gap.real_passable
    if agree:
        kind: Literal["ok", "missed_obstacle", "false_obstacle"] = "ok"
    elif sim_passable:
        kind = "missed_obstacle"  # thật không qua mà mô phỏng qua: vật cản bị bỏ sót
    else:
        kind = "false_obstacle"  # thật qua mà mô phỏng không qua: vật cản giả
    return GapResult(
        gap_id=gap.id,
        sim_width_m=sim_width,
        sim_passable=sim_passable,
        real_passable=gap.real_passable,
        agree=agree,
        kind=kind,
        heights_checked=len(heights),
    )


MeshParts = list[tuple[np.ndarray, np.ndarray]]


def _collider_local_mesh(collider: ColliderSpec, load_parts: Callable[[ColliderSpec], MeshParts]) -> MeshParts:
    """Lưới collider trong khung object-local: hộp theo kích thước, còn lại đọc GLB như Walk và USD."""
    if collider.collider_type in {ColliderType.AABB, ColliderType.OBB}:
        if collider.dimensions_xyz_m is None:
            raise ValueError(f"collider {collider.collider_id} thiếu kích thước hộp")
        box = trimesh.creation.box(extents=collider.dimensions_xyz_m)
        return [(np.asarray(box.vertices, dtype=float), np.asarray(box.faces, dtype=np.int64))]
    return load_parts(collider)


def _collider_world_pose(item: SceneObject, collider: ColliderSpec) -> tuple[Rotation, np.ndarray]:
    """Collider nằm trong object, object nằm trong canonical: t = t_obj + R_obj·t_local, R = R_obj·R_local."""
    object_rotation = Rotation.from_quat(item.transform.rotation_quaternion_xyzw)
    local = collider.local_transform
    translation = np.asarray(item.transform.translation_xyz, dtype=float) + object_rotation.apply(
        np.asarray(local.translation_xyz, dtype=float)
    )
    return object_rotation * Rotation.from_quat(local.rotation_quaternion_xyzw), translation


def compose_collision_world(
    objects: Sequence[SceneObject],
    background_vertices: np.ndarray,
    background_faces: np.ndarray,
    load_parts: Callable[[ColliderSpec], MeshParts],
) -> CollisionWorld:
    """Gộp môi trường đã khoét với collider của mọi vật mà USD và Walk xuất như vật (cùng quy tắc representation)."""
    vertex_blocks = [np.asarray(background_vertices, dtype=float)]
    face_blocks = [np.asarray(background_faces, dtype=np.int64)]
    owner_blocks = [np.full(len(face_blocks[0]), "", dtype=object)]
    part_blocks = [np.full(len(face_blocks[0]), -1, dtype=np.int64)]
    offset = len(vertex_blocks[0])
    solid: set[str] = set()
    solid_parts: set[int] = set()
    part_index = 0
    for item in objects:
        if not resolve_representation(item).export_as_object:
            continue
        if item.collider is None:
            raise ValueError(f"vật {item.id} được xuất nhưng chưa có collider")
        rotation, translation = _collider_world_pose(item, item.collider)
        closed = True
        for vertices, faces in _collider_local_mesh(item.collider, load_parts):
            world_vertices = rotation.apply(np.asarray(vertices, dtype=float)) + translation
            world_faces = np.asarray(faces, dtype=np.int64)
            part_closed = trimesh.Trimesh(world_vertices, world_faces, process=False).is_watertight
            closed = closed and part_closed
            if part_closed:
                solid_parts.add(part_index)
            vertex_blocks.append(world_vertices)
            face_blocks.append(world_faces + offset)
            owner_blocks.append(np.full(len(world_faces), item.id, dtype=object))
            part_blocks.append(np.full(len(world_faces), part_index, dtype=np.int64))
            offset += len(world_vertices)
            part_index += 1
        if closed:
            solid.add(item.id)
    mesh = trimesh.Trimesh(np.vstack(vertex_blocks), np.vstack(face_blocks), process=False)
    return CollisionWorld(
        mesh=mesh,
        face_owner=np.concatenate(owner_blocks),
        solid_owners=frozenset(solid),
        face_part=np.concatenate(part_blocks),
        solid_parts=frozenset(solid_parts),
    )


def collision_world(registry: ProjectRegistry, job_id: str, scene_revision: str) -> CollisionWorld:
    """Collision tổng hợp của một revision đã publish (không nhất thiết là revision hiện tại).

    Đọc, không ghi: không chạy phục hồi quyền sở hữu nguồn, nên revision cũ thiếu quyền sở hữu sẽ bị từ chối.
    """
    revision = registry.scene.revision(job_id, scene_revision)
    if revision is None:
        raise SceneError(f"revision {scene_revision} không thuộc job {job_id}")
    margin = _job_simulation_config(registry, job_id)["carve_margin_m"]
    background = effective_environment(registry, revision.scene, margin_m=margin)
    return compose_collision_world(
        revision.scene.objects,
        background.vertices,
        background.faces,
        lambda collider: load_mesh_parts(registry.runtime_resolver.require(collider.geometry_ref)),
    )


#: Vật được coi là đã dời khi dịch quá 1 cm hoặc quay quá 1° (quy tắc 4).
MOVE_TRANSLATION_M = 0.01
MOVE_ROTATION_DEG = 1.0
#: Hộp kiểm vết cũ thu vào 2 cm mỗi mặt để không tính nhầm mặt tiếp xúc của chính vật.
CLEARANCE_M = 0.02


class MoveResult(BaseModel):
    object_id: str
    old_cleared: bool
    new_present: bool
    passed: bool


def _moved(before: SceneObject, after: SceneObject) -> bool:
    shift = float(np.linalg.norm(np.subtract(after.transform.translation_xyz, before.transform.translation_xyz)))
    dot = abs(float(np.dot(before.transform.rotation_quaternion_xyzw, after.transform.rotation_quaternion_xyzw)))
    angle = math.degrees(2.0 * math.acos(min(1.0, dot)))
    return shift > MOVE_TRANSLATION_M or angle > MOVE_ROTATION_DEG


def _triangles_touch_box(triangles: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> bool:
    """Giao nhau tam giác–hộp trục song song (Akenine-Möller, vector hoá): tách bằng 3 trục hộp, pháp tuyến, 9 trục chéo."""
    if len(triangles) == 0:
        return False
    center = (lo + hi) / 2.0
    half = (hi - lo) / 2.0
    tris = triangles - center
    keep = np.all((tris.min(axis=1) <= half) & (tris.max(axis=1) >= -half), axis=1)
    tris = tris[keep]
    if not len(tris):
        return False
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    normal = np.cross(v1 - v0, v2 - v0)
    keep = np.abs(np.einsum("ij,ij->i", normal, v0)) <= np.abs(normal) @ half
    v0, v1, v2 = v0[keep], v1[keep], v2[keep]
    for edge in (v1 - v0, v2 - v1, v0 - v2):
        for axis in np.eye(3):
            axis_normal = np.cross(axis, edge)
            p0 = np.einsum("ij,ij->i", axis_normal, v0)
            p1 = np.einsum("ij,ij->i", axis_normal, v1)
            p2 = np.einsum("ij,ij->i", axis_normal, v2)
            radius = np.abs(axis_normal) @ half
            separated = (np.maximum(np.maximum(p0, p1), p2) < -radius) | (np.minimum(np.minimum(p0, p1), p2) > radius)
            v0, v1, v2 = v0[~separated], v1[~separated], v2[~separated]
            if not len(v0):
                return False
    return len(v0) > 0


def _old_pose_cleared(world_a: CollisionWorld, world_b: CollisionWorld, object_id: str, robot: RobotProfile) -> bool:
    """Vết cũ đã được khoét: không tam giác **môi trường** nào của world_b giao hộp tại pose A (trong dải z của robot).

    Chỉ xét môi trường: collider của vật khác (ghế dưới bàn, vật được dời tới chỗ cũ) có mặt ở đó là đúng, không phải vết sót.
    """
    owned = world_a.face_owner == object_id
    if not owned.any():
        return False
    points = world_a.mesh.vertices[np.unique(world_a.mesh.faces[owned])]
    lo = points.min(axis=0) + CLEARANCE_M
    hi = points.max(axis=0) - CLEARANCE_M
    if np.any(lo >= hi):
        return False  # vật quá nhỏ để thu hộp: không kiểm được, coi như chưa khoét
    lo[2] = max(lo[2], robot.height_min_m)
    hi[2] = min(hi[2], robot.height_max_m)
    if lo[2] >= hi[2]:
        return True  # vết cũ nằm ngoài dải cao của robot
    environment = world_b.mesh.triangles[world_b.face_owner == ""]
    return not _triangles_touch_box(environment, lo, hi)


def move_consistency(
    world_a: CollisionWorld,
    world_b: CollisionWorld,
    scene_a: SceneIR,
    scene_b: SceneIR,
    robot: RobotProfile,
) -> list[MoveResult]:
    """Kiểm nhất quán cho từng vật đã dời giữa bố trí A và B: vết cũ được khoét và collider mới có mặt."""
    before = {item.id: item for item in scene_a.objects}
    after = {item.id: item for item in scene_b.objects}
    results: list[MoveResult] = []
    for object_id in sorted(before.keys() & after.keys()):
        if not _moved(before[object_id], after[object_id]):
            continue
        old_cleared = _old_pose_cleared(world_a, world_b, object_id, robot)
        new_present = bool(np.any(world_b.face_owner == object_id))
        results.append(
            MoveResult(
                object_id=object_id,
                old_cleared=old_cleared,
                new_present=new_present,
                passed=old_cleared and new_present,
            )
        )
    return results
