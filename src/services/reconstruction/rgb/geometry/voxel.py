"""Config REC-05; không suy mét, footprint hoặc opacity từ defaults upstream."""

import hashlib
import math
from typing import Literal, Self

from pydantic import Field, FiniteFloat, SerializerFunctionWrapHandler, model_serializer, model_validator

from src.models.contracts.artifacts import ContractModel
from src.models.contracts.identity import canonical_json_bytes

Vector3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
MAX_VOXEL_CELLS = 1_500_000_000


class StatisticalOutlierRemovalConfig(ContractModel):
    """Opt-in metric-space SOR with explicit neighbor and memory bounds."""

    neighbors: int = Field(ge=2, le=64, strict=True)
    standard_deviation_ratio: FiniteFloat = Field(gt=0)
    max_gaussians: int = Field(ge=3, le=5_000_000, strict=True)

    @model_validator(mode="after")
    def _enough_rows_for_neighbors(self) -> Self:
        if self.max_gaussians <= self.neighbors:
            raise ValueError("SOR max_gaussians must exceed the neighbor count")
        return self


class VoxelConfig(ContractModel):
    """Seeds thuộc canonical Z-up; cluster seed và capsule seed có vai trò riêng."""

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    resolution_m: FiniteFloat = Field(default=0.05, gt=0)
    opacity: FiniteFloat = Field(gt=0, lt=1)
    cluster_resolution_m: FiniteFloat = Field(gt=0)
    cluster_opacity: FiniteFloat = Field(gt=0, lt=1)
    cluster_min_contribution: FiniteFloat = Field(ge=0)
    cluster_seed_world: Vector3
    navigation_seed_world: Vector3
    capsule_height_m: FiniteFloat = Field(gt=0)
    capsule_radius_m: FiniteFloat = Field(gt=0)
    # ADR 0001 amendment 2026-09-27: seed bị vật cản được tìm lại trong vùng không
    # khí liên thông, nhưng chỉ trong ngưỡng này. Không có ứng viên thì từ chối.
    max_seed_relocation_m: FiniteFloat = Field(default=1.0, gt=0)
    gpu_index: int = Field(ge=0, strict=True)
    #: Vùng làm việc canonical (min, max). Brush có thể sinh Gaussian rác cách hàng trăm mét
    #: làm lưới voxel phình và rỗng; cắt bằng `--filter-box` của upstream trước khi lọc cụm.
    crop_box_world: tuple[Vector3, Vector3] | None = None
    #: Bước dọn Gaussian rác trước voxel hoá. `cluster`: giữ cụm liên thông tại seed (cần 3DGS
    #: dày). `floaters`: bỏ Gaussian không góp vào voxel đặc nào — hiệu chỉnh 2026-09-30 trên
    #: Aisle_CW: preview thưa (~98k Gaussian) vỡ thành hàng trăm cụm nên `cluster` xoá gần hết.
    cleanup: Literal["cluster", "floaters"] = "cluster"
    #: Disabled unless a versioned product geometry profile explicitly opts in.
    statistical_outlier_removal: StatisticalOutlierRemovalConfig | None = None
    #: Giới hạn log-scale tối đa của Gaussian để tránh floaters khổng lồ làm phình lưới voxel.
    max_gaussian_scale_log: FiniteFloat | None = None
    external_fill_size_m: FiniteFloat | None = Field(default=None, gt=0)

    @model_serializer(mode="wrap")
    def _versioned_payload(self, handler: SerializerFunctionWrapHandler) -> dict:
        """Preserve legacy receipt bytes and hashes when reading schema 1.0/1.1."""
        payload = handler(self)
        if self.schema_version != "1.2":
            payload.pop("external_fill_size_m", None)
        return payload

    @model_validator(mode="after")
    def _crop_order(self) -> Self:
        if self.crop_box_world is not None:
            low, high = self.crop_box_world
            if any(a >= b for a, b in zip(low, high, strict=True)):
                raise ValueError("crop box min phải nhỏ hơn max trên mọi trục")
        if self.statistical_outlier_removal is not None and self.schema_version not in ("1.1", "1.2"):
            raise ValueError("statistical outlier removal requires VoxelConfig schema 1.1 or 1.2")
        if self.external_fill_size_m is not None and self.schema_version != "1.2":
            raise ValueError("external fill requires VoxelConfig schema 1.2")
        return self

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


def _crop_arguments(config: VoxelConfig) -> tuple[str, ...]:
    """`--filter-box` trong hệ native Y-up (sau hai phép xoay), từ 8 góc của box canonical."""
    if config.crop_box_world is None:
        return ()
    low, high = config.crop_box_world
    corners = [
        native_from_world((x, y, z)) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])
    ]
    native_low = [min(corner[axis] for corner in corners) for axis in range(3)]
    native_high = [max(corner[axis] for corner in corners) for axis in range(3)]
    return ("--filter-box", ",".join(str(value) for value in (*native_low, *native_high)))


def cluster_command(config: VoxelConfig, *, input_filename: str = "input.ply") -> tuple[str, ...]:
    """Input PLY raw xyz đã canonical; bỏ PLY flip rồi đổi sang native Y-up."""
    cluster = f"{config.cluster_resolution_m},{config.cluster_opacity},{config.cluster_min_contribution}"
    scale_filters = (
        (
            "--filter-value",
            f"scale_0,lte,{config.max_gaussian_scale_log}",
            "--filter-value",
            f"scale_1,lte,{config.max_gaussian_scale_log}",
            "--filter-value",
            f"scale_2,lte,{config.max_gaussian_scale_log}",
        )
        if config.max_gaussian_scale_log is not None
        else ()
    )
    return (
        input_filename,
        "--gpu",
        str(config.gpu_index),
        "--rotate",
        "0,0,180",
        "--rotate",
        "-90,0,0",
        *_crop_arguments(config),
        *scale_filters,
        *(
            ("--filter-floaters", cluster)
            if config.cleanup == "floaters"
            else ("--seed-pos", _vector(native_from_world(config.cluster_seed_world)), "--filter-cluster", cluster)
        ),
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
        *_fill_arguments(config),
        "--seed-pos",
        _vector(native_from_world(config.navigation_seed_world)),
        "--voxel-carve",
        f"{config.capsule_height_m},{config.capsule_radius_m}",
        "--collision-mesh",
        "smooth",
        "geometry.voxel.json",
    )


def occupancy_command(config: VoxelConfig) -> tuple[str, ...]:
    """Occupancy after the configured fill, before capsule carve or seed relocation."""
    return (
        "cluster.ply",
        "--gpu",
        str(config.gpu_index),
        "--voxel-size",
        str(config.resolution_m),
        "--voxel-opacity",
        str(config.opacity),
        *_fill_arguments(config),
        *(
            ("--seed-pos", _vector(native_from_world(config.navigation_seed_world)))
            if config.external_fill_size_m
            else ()
        ),
        "occupancy.voxel.json",
    )


def _fill_arguments(config: VoxelConfig) -> tuple[str, ...]:
    return ("--voxel-external-fill", str(config.external_fill_size_m)) if config.external_fill_size_m else ()


def require_voxel_capacity(lengths: Vector3, resolution_m: float, fill_size_m: float) -> None:
    """Bound padded grid cells, including the pinned runtime's four-voxel alignment."""
    if not all(math.isfinite(value) and value >= 0 for value in lengths):
        raise ValueError("invalid Gaussian extent for voxel capacity")
    try:
        padding = (math.ceil(fill_size_m / resolution_m) + 1) * resolution_m
        block = 4 * resolution_m
        cells = math.prod((math.ceil((length + 2 * padding) / block) + 1) * 4 for length in lengths)
    except OverflowError as error:
        raise ValueError("external fill exceeds finite voxel capacity") from error
    if cells > MAX_VOXEL_CELLS:
        raise ValueError("external fill exceeds voxel capacity; reduce crop or explicitly choose a coarser profile")
