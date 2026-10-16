"""Máy đo P2/P3 (architecture §15.3 quy tắc 3–4): tính sai số đoạn đo, bề rộng khe và nhất quán sau khi dời.

Các hàm đo là thuần tính toán: cùng đầu vào cho cùng kết quả, không ghi gì và không đọc ground truth.
Toạ độ theo khung canonical của scene (mét, Z-up, sàn z = 0).
"""

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import trimesh
from pydantic import BaseModel

from src.services.orchestration.value.ground_truth import GapCheck, MeasuredDistance, RobotProfile

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
    #: Vật có mọi thành phần collider kín; chỉ các vật này mới có "bên trong" để kiểm điểm giữa khe.
    solid_owners: frozenset[str]


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
    """Điểm nằm trong một vật kín khi tia đi ra cắt số lẻ mặt của vật đó."""
    faces = world.mesh.triangles
    for owner in world.solid_owners:
        owned = faces[world.face_owner == owner]
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
