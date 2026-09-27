"""Quyết định seed trước native carve, vốn có thể relocate hoặc skip âm thầm.

Luồng: đọc occupancy không carve từ cùng immutable cluster, dựng đúng kernel làm
tròn của carve 3.6.6, rồi hỏi seed search trong vùng không khí liên thông. Kết quả
luôn ghi cả seed đã yêu cầu lẫn seed được chấp nhận; nếu seed đã hợp lệ thì
`relocates` là False và hai điểm trùng nhau.
"""

import hashlib
from pathlib import Path

from src.services.reconstruction.adapters.voxel_octree import VoxelOctree
from src.services.reconstruction.adapters.voxel_output import VoxelMetadata, write_evidence
from src.services.reconstruction.adapters.voxel_seed_search import (
    SeedSearchPlan,
    SeedSearchResult,
    find_connected_seed,
    search_plan,
)
from src.services.reconstruction.rgb.voxel import VoxelConfig


def validate_seed_clearance(workspace: Path, config: VoxelConfig) -> dict:
    """Kiểm đúng box dilation kernel native; không suy clearance từ camera center."""
    metadata_bytes = (workspace / "occupancy.voxel.json").read_bytes()
    metadata = VoxelMetadata.model_validate_json(metadata_bytes)
    if metadata.asset != {"generator": "splat-transform v3.6.6"}:
        raise ValueError("unexpected occupancy producer")
    if metadata.voxel_resolution != config.resolution_m:
        raise ValueError("occupancy resolution differs from requested config")
    payload = (workspace / "occupancy.voxel.bin").read_bytes()
    plan = search_plan(VoxelOctree(metadata, payload), config)
    result = find_connected_seed(plan)
    receipt = _receipt(config, plan, result, metadata_bytes, payload)
    write_evidence(workspace / "seed-clearance.json", receipt)
    return receipt


def _receipt(
    config: VoxelConfig,
    plan: SeedSearchPlan,
    result: SeedSearchResult,
    metadata_bytes: bytes,
    payload: bytes,
) -> dict:
    """Evidence phải đủ để consumer tự dựng lại kernel và tự kiểm lại quyết định."""
    return dict(
        schema_version="1.0",
        status="VALID",
        method="splat_3.6.6_separable_box_dilation",
        search_method="connected_free_region_bfs6",
        config_checksum=config.checksum(),
        requested_seed_world=list(config.navigation_seed_world),
        accepted_seed_world=_accepted_seed(config, plan, result),
        relocates=result.relocates,
        relocation_steps_voxels=result.steps,
        relocation_distance_m=round(result.steps * plan.resolution, 6),
        escape_hops_voxels=result.escape_hops,
        reachable_cells=result.reachable_cells,
        relocation_bound_m=config.max_seed_relocation_m,
        accepted_seed_cell=list(result.cell),
        kernel_low=list(plan.kernel(result.cell).low),
        kernel_high=list(plan.kernel(result.cell).high),
        occupancy_metadata_checksum="sha256:" + hashlib.sha256(metadata_bytes).hexdigest(),
        occupancy_binary_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
    )


def _accepted_seed(config: VoxelConfig, plan: SeedSearchPlan, result: SeedSearchResult) -> list:
    """Không relocate thì giữ đúng seed đã yêu cầu, không dùng tâm ô đã làm tròn.

    Tâm ô suy lại từ grid là mất thông tin: nó có thể lệch vài mm so với seed gốc, và
    khiến `relocates=false` mà hai điểm vẫn khác nhau — vi phạm chính invariant mà
    shared `SeedDecision` kiểm.
    """
    if not result.relocates:
        return list(config.navigation_seed_world)
    return list(plan.world(result.cell))
