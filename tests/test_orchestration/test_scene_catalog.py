"""Danh mục vật + vật lý mặc định (ADR 0007 chặng 8)."""

import pytest

from src.models.contracts.scene import MassSource
from src.services.orchestration.scene.catalog import load_catalog, physics_for, suggest_classes


def test_catalog_lists_placeable_isaac_classes_with_real_sizes() -> None:
    catalog = load_catalog()

    assert {"pallet", "box", "crate", "rack"} <= set(catalog.classes())
    assert "wall" not in catalog.classes() and "floor" not in catalog.classes()
    pallet = catalog.family("SM_PaletteA")
    assert pallet is not None and pallet.size_xyz_m == pytest.approx((1.2132, 1.0029, 0.2111), abs=1e-3)


def test_physics_prefers_user_mass_then_class_default_then_density() -> None:
    assert physics_for("pallet", 0.2, mass_kg=31.5).mass_source == MassSource.USER
    default = physics_for("pallet", 0.2)
    assert (default.mass_kg, default.mass_source) == (25.0, MassSource.CATALOG_DEFAULT)
    by_density = physics_for("box", 0.1)
    assert by_density.mass_source == MassSource.CATALOG_DENSITY
    assert by_density.mass_kg == pytest.approx(by_density.density_kg_m3 * 0.1)


def test_static_class_has_no_mass_and_unknown_class_falls_back_to_density() -> None:
    rack = physics_for("rack", 2.0)
    assert rack.dynamic is False and rack.mass_kg is None and rack.mass_source is None

    unknown = physics_for("khong-co-trong-danh-muc", 0.5)
    assert unknown.dynamic and unknown.mass_source == MassSource.CATALOG_DENSITY and unknown.mass_kg > 0


def test_missing_volume_still_yields_positive_mass() -> None:
    assert physics_for("box", None).mass_kg > 0


def test_size_suggestion_ranks_matching_class_first() -> None:
    assert suggest_classes((1.2, 1.0, 0.2))[0] == "pallet"
    assert suggest_classes((1.0, 0.2, 1.2))[0] == "pallet"  # không phụ thuộc hướng đặt
