"""Danh mục vật (nhãn, kích thước, asset Isaac, vật lý mặc định) cho pipeline v2 (ADR 0007 chặng 8).

Nguồn: `configs/product/object_catalog_v1.json`, sinh bằng `scripts/scene/build_isaac_catalog.py`
từ thư viện asset kho công khai của Isaac Sim. Giá trị vật lý là **mặc định tham khảo** (asset
Isaac không có khối lượng); người dùng sửa được và nguồn số luôn được ghi (`MassSource`).
"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import ConfigDict

from src.models.contracts.artifacts import ContractModel
from src.models.contracts.scene import MassSource, ObjectPhysics

CATALOG_PATH = Path(__file__).resolve().parents[4] / "configs/product/object_catalog_v1.json"
#: Vật chưa có nhãn trong danh mục: mật độ khối bao giả định (kg/m³) và ma sát trung tính.
_UNKNOWN = {
    "dynamic": True,
    "density_kg_m3": 150.0,
    "static_friction": 0.5,
    "dynamic_friction": 0.4,
    "restitution": 0.1,
}


class CatalogEntry(ContractModel):
    """Một họ asset trong danh mục."""

    model_config = ConfigDict(extra="ignore")

    family: str
    asset_url: str
    semantic_class: str | None
    placeable: bool
    size_xyz_m: tuple[float, float, float]
    up_axis: str
    physics: dict


class Catalog(ContractModel):
    """Toàn bộ danh mục + chú thích nguồn."""

    model_config = ConfigDict(extra="ignore")

    catalog: str
    version: int
    source: str
    physics_note: str
    entries: list[CatalogEntry]

    def placeable(self) -> list[CatalogEntry]:
        """Các họ asset đặt được làm vật trong scene."""
        return [entry for entry in self.entries if entry.placeable]

    def classes(self) -> list[str]:
        """Nhãn lớp đặt được, không trùng, theo thứ tự chữ cái."""
        return sorted({entry.semantic_class for entry in self.placeable() if entry.semantic_class})

    def family(self, name: str) -> CatalogEntry | None:
        """Tra một họ asset theo tên."""
        return next((entry for entry in self.entries if entry.family == name), None)

    def defaults(self, semantic_class: str | None) -> dict:
        """Giá trị vật lý mặc định của một nhãn (họ đầu tiên mang nhãn đó)."""
        match = next((entry for entry in self.entries if entry.semantic_class == semantic_class), None)
        return dict(match.physics) if match and semantic_class else dict(_UNKNOWN)


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    """Đọc danh mục một lần cho tiến trình."""
    return Catalog.model_validate(json.loads(CATALOG_PATH.read_text(encoding="utf-8")))


def suggest_classes(dimensions_xyz_m: tuple[float, float, float], limit: int = 3) -> list[str]:
    """Gợi ý nhãn theo kích thước hộp bao (không phân biệt hướng); người dùng vẫn phải xác nhận.

    So ba cạnh đã sắp của vật với từng họ asset; điểm = sai lệch tương đối lớn nhất. Đây là gợi ý
    hình học thô — không nhìn hình ảnh — nên chỉ dùng để sắp thứ tự danh sách chọn.
    """
    target = sorted(dimensions_xyz_m)
    scored: dict[str, float] = {}
    for entry in load_catalog().placeable():
        if not entry.semantic_class:
            continue
        size = sorted(entry.size_xyz_m)
        error = max(abs(a - b) / max(b, 1e-3) for a, b in zip(target, size, strict=True))
        scored[entry.semantic_class] = min(error, scored.get(entry.semantic_class, error))
    return [name for name, _ in sorted(scored.items(), key=lambda item: item[1])[:limit]]


def physics_for(semantic_class: str | None, volume_m3: float | None, mass_kg: float | None = None) -> ObjectPhysics:
    """Vật lý cho một vật: khối lượng người dùng nhập > khối lượng mặc định của nhãn > mật độ × thể tích."""
    defaults = load_catalog().defaults(semantic_class)
    dynamic = bool(defaults.get("dynamic", True))
    density = defaults.get("density_kg_m3")
    source: MassSource | None = None
    mass: float | None = None
    if dynamic:
        if mass_kg is not None:
            mass, source = float(mass_kg), MassSource.USER
        elif defaults.get("mass_kg") is not None:
            mass, source = float(defaults["mass_kg"]), MassSource.CATALOG_DEFAULT
        else:
            # Thể tích thiếu/không dương (vật quá mỏng): lấy 1 lít để khối lượng vẫn dương, ghi rõ nguồn.
            mass = max(float(density or _UNKNOWN["density_kg_m3"]) * max(volume_m3 or 0.0, 1e-3), 0.05)
            source = MassSource.CATALOG_DENSITY
    return ObjectPhysics(
        dynamic=dynamic,
        mass_kg=mass,
        mass_source=source,
        density_kg_m3=float(density) if density else None,
        static_friction=float(defaults.get("static_friction", 0.5)),
        dynamic_friction=float(defaults.get("dynamic_friction", 0.4)),
        restitution=float(defaults.get("restitution", 0.1)),
        provenance={
            "semantic_class": semantic_class,
            "volume_m3": volume_m3,
            "note": defaults.get("note", "nhãn chưa có trong danh mục; mật độ khối bao giả định"),
        },
    )
