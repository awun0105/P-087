"""Simulation controls shared with the standalone USD runtime, using only stdlib."""

import math
from collections.abc import Mapping


def physics_build_config(values: Mapping[str, object]) -> dict[str, bool | float]:
    """Validate physical controls without rejecting unrelated build metadata."""
    ground = values.get("ground_plane", True)
    if not isinstance(ground, bool):
        raise ValueError("ground_plane must be a boolean")
    result: dict[str, bool | float] = {"ground_plane": ground}
    for key, default in (
        ("static_friction", 0.5),
        ("dynamic_friction", 0.4),
        ("restitution", 0.0),
        ("carve_margin_m", 0.05),
    ):
        value = values.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            raise ValueError(f"{key} must be finite and numeric")
        if value < 0 or (key == "restitution" and value > 1):
            raise ValueError(f"{key} is outside its physical range")
        result[key] = float(value)
    return result
