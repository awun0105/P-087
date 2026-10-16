"""T-043 bước 6: giới hạn cứng nâng lên làm lưới cuối; file mẫu và image giữ cùng giá trị."""

from pathlib import Path

from src.services.reconstruction.adapters.brush_runtime import BrushRuntimeSettings
from src.services.reconstruction.adapters.colmap_runtime import ColmapRuntimeSettings

ROOT = Path(__file__).resolve().parents[2]


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
