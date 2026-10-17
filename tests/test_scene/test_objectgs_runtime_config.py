"""Cấu hình runtime ObjectGS: cache extension dựng sẵn đi từ Settings tới ObjectGSRuntime (T-037)."""

from pathlib import Path

from src.config import Settings
from src.services.orchestration.scene.objectify import ObjectifyConfig, objectgs_runtime_for


def _settings(tmp_path: Path, **extra: object) -> Settings:
    return Settings(
        product_objectgs_runtime_python=tmp_path / "python" / "bin" / "python",
        product_objectgs_repository=tmp_path / "ObjectGS",
        product_objectgs_gsplat_repository=tmp_path / "gsplat-object",
        **extra,
    )


def test_extension_cache_from_settings_reaches_runtime(tmp_path: Path) -> None:
    cache = tmp_path / "torch_extensions"
    runtime = objectgs_runtime_for(
        _settings(tmp_path, product_objectgs_extension_cache_dir=cache), ObjectifyConfig.model_validate({})
    )
    assert runtime.extension_cache_dir == cache


def test_without_extension_cache_runtime_keeps_old_behaviour(tmp_path: Path) -> None:
    runtime = objectgs_runtime_for(_settings(tmp_path), ObjectifyConfig.model_validate({}))
    assert runtime.extension_cache_dir is None
