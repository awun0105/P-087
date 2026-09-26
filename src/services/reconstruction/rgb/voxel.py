"""Config REC-05; không suy mét, footprint hoặc opacity từ defaults upstream."""

import hashlib
from typing import Literal

from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ContractModel
from src.models.contracts.identity import canonical_json_bytes

Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]


class VoxelConfig(ContractModel):
    """Seeds thuộc canonical Z-up; cluster seed và capsule seed có vai trò riêng."""

    schema_version: Literal["1.0"] = "1.0"
    resolution_m: FiniteFloat = Field(default=0.05, gt=0)
    opacity: FiniteFloat = Field(gt=0, lt=1)
    cluster_resolution_m: FiniteFloat = Field(gt=0)
    cluster_opacity: FiniteFloat = Field(gt=0, lt=1)
    cluster_min_contribution: FiniteFloat = Field(ge=0)
    cluster_seed_world: Vector3
    navigation_seed_world: Vector3
    capsule_height_m: FiniteFloat = Field(gt=0)
    capsule_radius_m: FiniteFloat = Field(gt=0)
    gpu_index: int = Field(ge=0, strict=True)

    def checksum(self) -> str:
        """Bind toàn bộ knobs/footprint/seed với evidence của attempt."""
        return "sha256:" + hashlib.sha256(canonical_json_bytes(self)).hexdigest()


def native_from_world(point: Vector3) -> Vector3:
    """R_x(-90°): canonical Z-up sang native Y-up, giữ handedness và đơn vị."""
    x, y, z = point
    return x, z, -y


def world_from_native(point: Vector3) -> Vector3:
    """Inverse thuần rotation; không áp metric scale lần hai."""
    x, y, z = point
    return x, -z, y


def _vector(point: Vector3) -> str:
    return ",".join(str(value) for value in point)


def cluster_command(config: VoxelConfig) -> tuple[str, ...]:
    """Input PLY raw xyz đã canonical; bỏ PLY flip rồi đổi sang native Y-up."""
    cluster = f"{config.cluster_resolution_m},{config.cluster_opacity},{config.cluster_min_contribution}"
    return (
        "input.ply",
        "--gpu",
        str(config.gpu_index),
        "--rotate",
        "0,0,180",
        "--rotate",
        "-90,0,0",
        "--seed-pos",
        _vector(native_from_world(config.cluster_seed_world)),
        "--filter-cluster",
        cluster,
        "cluster.ply",
    )


def collision_command(config: VoxelConfig) -> tuple[str, ...]:
    """.glb trực tiếp là visual export; voxel writer mới tạo collision mesh."""
    return (
        "cluster.ply",
        "--gpu",
        str(config.gpu_index),
        "--voxel-size",
        str(config.resolution_m),
        "--voxel-opacity",
        str(config.opacity),
        "--seed-pos",
        _vector(native_from_world(config.navigation_seed_world)),
        "--voxel-carve",
        f"{config.capsule_height_m},{config.capsule_radius_m}",
        "--collision-mesh",
        "smooth",
        "geometry.voxel.json",
    )
