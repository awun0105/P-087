"""T-043 bước 6: giới hạn cứng nâng lên làm lưới cuối; file mẫu và image giữ cùng giá trị."""

from pathlib import Path

from src.config import Settings
from src.services.reconstruction.adapters.brush_runtime import BrushRuntimeSettings
from src.services.reconstruction.adapters.colmap_runtime import ColmapRuntimeSettings
from src.services.reconstruction.adapters.voxel_runtime import VoxelRuntimeSettings

ROOT = Path(__file__).resolve().parents[2]
#: Số lần gọi voxel trong một lượt finalize: qualify, inspect, cluster, inspect-cluster, occupancy, collision
#: (src/services/reconstruction/adapters/voxel.py:165–199). Mỗi lần có giới hạn riêng của VoxelRuntimeSettings.
VOXEL_CALLS_PER_FINALIZE = 6


def test_hard_limits_are_the_last_net_defaults() -> None:
    assert ColmapRuntimeSettings(runtime_identity="fixture").timeout_seconds == 14400
    assert BrushRuntimeSettings(expected_version="0.3.0", runtime_identity="fixture").timeout_seconds == 21600
    assert BrushRuntimeSettings(expected_version="0.3.0", runtime_identity="fixture").hang_timeout_seconds == 180


def test_image_entrypoint_and_example_env_use_the_new_hard_limits() -> None:
    entrypoint = (ROOT / "scripts/gpu/docker_entrypoint.sh").read_text(encoding="utf-8")
    example = (ROOT / "scripts/gpu/studio.env.example").read_text(encoding="utf-8")
    assert "R2S_COLMAP_TIMEOUT_SECONDS:-14400" in entrypoint
    assert "R2S_BRUSH_TIMEOUT_SECONDS:-21600" in entrypoint
    assert "R2S_COLMAP_TIMEOUT_SECONDS=14400" in example
    assert "R2S_BRUSH_TIMEOUT_SECONDS=21600" in example


def test_preview_outer_limit_covers_colmap_then_brush_in_one_tool_run() -> None:
    """Round 2 (review mục 1): bước preview chạy COLMAP rồi Brush trong một `_run_tool`; giới hạn bao ngoài phải lớn hơn tổng."""
    preview = Settings.model_fields["product_preview_timeout_seconds"].default
    colmap = ColmapRuntimeSettings.model_fields["timeout_seconds"].default
    brush = BrushRuntimeSettings.model_fields["timeout_seconds"].default
    assert preview >= colmap + brush


def test_finalize_outer_limit_covers_brush_splat_and_voxel_calls() -> None:
    """Round 2: finalize chạy splat-process qua Brush (một lần) và voxel (VOXEL_CALLS_PER_FINALIZE lần) trong một `_run_tool`."""
    finalize = Settings.model_fields["product_finalize_timeout_seconds"].default
    brush = BrushRuntimeSettings.model_fields["timeout_seconds"].default
    voxel = VoxelRuntimeSettings.model_fields["timeout_seconds"].default
    assert finalize >= brush + VOXEL_CALLS_PER_FINALIZE * voxel


def test_image_entrypoint_and_example_env_match_the_preview_outer_limit() -> None:
    entrypoint = (ROOT / "scripts/gpu/docker_entrypoint.sh").read_text(encoding="utf-8")
    example = (ROOT / "scripts/gpu/studio.env.example").read_text(encoding="utf-8")
    assert "PRODUCT_PREVIEW_TIMEOUT_SECONDS:-36000" in entrypoint
    assert "PRODUCT_PREVIEW_TIMEOUT_SECONDS=36000" in example
