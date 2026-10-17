"""Tên biến môi trường của runtime ngoài: tên theo chức năng (`R2S_*`), vẫn nhận tên cũ theo mã task (`RECxx_*`).

Tên cũ chỉ để máy và file env chưa đổi tiếp tục chạy. Mỗi tên cũ thật sự được dùng sẽ ghi một cảnh báo (một lần mỗi tên).
Khi cả tên mới và tên cũ cùng có, tên mới thắng.
"""

import logging
import os
from collections.abc import Mapping
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, EnvSettingsSource, PydanticBaseSettingsSource

#: Tiền tố mới → tiền tố cũ. Nguồn duy nhất của bảng đổi tên.
LEGACY_PREFIXES: dict[str, str] = {
    "R2S_COLMAP_": "REC03_COLMAP_",
    "R2S_BRUSH_": "REC04_BRUSH_",
    "R2S_SPLAT_": "REC04_SPLAT_",
    "R2S_VOXEL_": "REC05_VOXEL_",
    "R2S_MOGE_": "REC06_MOGE_",
    "R2S_LIDAR_ODOMETRY_": "REC17_LIDAR_ODOMETRY_",
}

_warned: set[str] = set()
_log = logging.getLogger(__name__)


def reset_warnings() -> None:
    """Chỉ dùng trong test: cho phép cảnh báo lại từ đầu."""
    _warned.clear()


def _warn(old: str, new: str) -> None:
    if old not in _warned:
        _warned.add(old)
        _log.warning("Biến môi trường %s là tên cũ, sẽ bỏ; đổi thành %s", old, new)


def legacy_name(new: str) -> str | None:
    """Tên cũ tương ứng với một tên mới, hoặc None nếu tên không thuộc bảng đổi tên."""
    for prefix, old_prefix in LEGACY_PREFIXES.items():
        if new.startswith(prefix):
            return old_prefix + new[len(prefix) :]
    return None


def requirement_env_name(old: str) -> str:
    """Khoá `requires` của bản ghi cũ (tên RECxx_) đổi sang tên mới; tên không thuộc bảng thì giữ nguyên."""
    for prefix, old_prefix in LEGACY_PREFIXES.items():
        if old.startswith(old_prefix):
            return prefix + old[len(old_prefix) :]
    return old


def runtime_env(env: Mapping[str, str], new: str, default: str = "") -> str:
    """Cho script đọc thẳng dict môi trường: tên mới trước, rồi tên cũ (kèm cảnh báo), rồi `default`."""
    value = env.get(new, "").strip()
    if value:
        return value
    old = legacy_name(new)
    if old is not None and env.get(old, "").strip():
        _warn(old, new)
        return env[old].strip()
    return default


class _LegacyEnvSource(EnvSettingsSource):
    """Nguồn env với tiền tố cũ: chỉ có tác dụng khi tên mới không có trong môi trường."""

    def __init__(self, settings_cls: type[BaseSettings], *, new_prefix: str, legacy_prefix: str) -> None:
        super().__init__(settings_cls, env_prefix=legacy_prefix)
        self._new_prefix = new_prefix
        self._legacy_prefix = legacy_prefix

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        value, key, is_complex = super().get_field_value(field, field_name)
        if value is not None:
            new = (self._new_prefix + field_name).upper()
            if os.environ.get(new) is None:
                _warn((self._legacy_prefix + field_name).upper(), new)
            else:
                # Tên mới có mặt và sẽ thắng ở nguồn trước; không đụng tới nguồn cũ.
                return None, key, is_complex
        return value, key, is_complex


class RuntimeSettings(BaseSettings):
    """Lớp cha của settings runtime: đọc `R2S_<X>_*`; thiếu thì đọc tên cũ `RECxx_<X>_*` (có cảnh báo)."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        new_prefix = str(settings_cls.model_config["env_prefix"])
        legacy = _LegacyEnvSource(settings_cls, new_prefix=new_prefix, legacy_prefix=LEGACY_PREFIXES[new_prefix])
        return (init_settings, env_settings, legacy, dotenv_settings, file_secret_settings)


__all__ = [
    "LEGACY_PREFIXES",
    "RuntimeSettings",
    "legacy_name",
    "requirement_env_name",
    "reset_warnings",
    "runtime_env",
]
