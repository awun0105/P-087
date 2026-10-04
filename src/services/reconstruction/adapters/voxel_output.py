"""Validation native voxel metadata/binary trước canonical collision derivative."""

import json
import math
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from src.models.contracts.artifacts import ContractModel
from src.services.reconstruction.rgb.geometry.voxel import Vector3, VoxelConfig


class VoxelBounds(ContractModel):
    """Bounds native Y-up; không gán nhãn canonical cho metadata của upstream."""

    min: Vector3
    max: Vector3

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if any(low >= high for low, high in zip(self.min, self.max)):
            raise ValueError("voxel bounds must have positive extent")
        return self


class VoxelMetadata(ContractModel):
    """Format native 1.1 của pinned splat-transform, không phải shared artifact."""

    version: Literal["1.1"]
    asset: dict[str, Literal["splat-transform v3.6.6"]]
    grid_bounds: VoxelBounds = Field(alias="gridBounds")
    scene_bounds: VoxelBounds = Field(alias="sceneBounds")
    voxel_resolution: float = Field(alias="voxelResolution", gt=0, allow_inf_nan=False)
    leaf_size: Literal[4] = Field(alias="leafSize")
    tree_depth: int = Field(alias="treeDepth", ge=0, strict=True)
    num_interior_nodes: int = Field(alias="numInteriorNodes", ge=0, strict=True)
    num_mixed_leaves: int = Field(alias="numMixedLeaves", ge=0, strict=True)
    node_count: int = Field(alias="nodeCount", gt=0, strict=True)
    leaf_data_count: int = Field(alias="leafDataCount", ge=0, strict=True)


def validate_voxel_output(workspace: Path, config: VoxelConfig) -> VoxelMetadata:
    """Kiểm resolution, bounds và byte layout; chưa thay topology/physics proof."""
    metadata = VoxelMetadata.model_validate_json((workspace / "geometry.voxel.json").read_bytes())
    if metadata.asset != {"generator": "splat-transform v3.6.6"}:
        raise ValueError("unexpected voxel producer")
    if not math.isclose(metadata.voxel_resolution, config.resolution_m, rel_tol=1e-12):
        raise ValueError("voxel resolution differs from requested config")
    size = (workspace / "geometry.voxel.bin").stat().st_size
    if size != 4 * (metadata.node_count + metadata.leaf_data_count):
        raise ValueError("voxel binary length differs from metadata")
    # Node pointers/occupancy semantics vẫn thuộc upstream reader/EX-SIM qualification.
    return metadata


def write_evidence(path: Path, evidence: dict) -> None:
    """Private attempt evidence không overwrite và không nhận NaN JSON."""
    payload = json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False)
    with path.open("x") as stream:
        stream.write(payload + "\n")
