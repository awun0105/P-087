"""Dựng danh mục vật từ thư viện asset kho công khai của Isaac Sim (ADR 0007, chặng 8).

Chạy trong runtime có `usd-core` (`data/scene_runtime`), cần mạng. Mỗi họ asset (bỏ hậu tố số của
bản sao) lấy một file đại diện; đọc nhãn `semantic:*`/`LabelsAPI`, kích thước bao thật (mét) và trục
lên. Giá trị vật lý mặc định **không** có trong asset (đã kiểm: không có MassAPI) — ghép từ
`PHYSICS_DEFAULTS` bên dưới, gắn rõ là giá trị tham khảo để người dùng sửa.

    data/scene_runtime/bin/python scripts/scene/build_isaac_catalog.py \\
        --out configs/product/object_catalog_v1.json
"""

import argparse
import json
import re
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from pxr import Usd, UsdGeom

BUCKET = "https://omniverse-content-production.s3-us-west-2.amazonaws.com"
PREFIX = "Assets/Isaac/5.1/Isaac/Environments/Simple_Warehouse/Props/"
_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

# Giá trị tham khảo, không phải số đo: khối lượng điển hình hoặc mật độ khối bao, ma sát trên sàn
# bê tông. `dynamic=False` = vật cố định trong kho (kệ, dầm) → collider tĩnh. Người dùng sửa được
# trong Studio; nguồn ghi vào provenance là "catalog_default".
PHYSICS_DEFAULTS: dict[str, dict[str, object]] = {
    "pallet": {
        "dynamic": True,
        "mass_kg": 25.0,
        "static_friction": 0.6,
        "dynamic_friction": 0.5,
        "restitution": 0.1,
        "note": "pallet gỗ tiêu chuẩn khoảng 25 kg",
    },
    "box": {
        "dynamic": True,
        "density_kg_m3": 150.0,
        "static_friction": 0.5,
        "dynamic_friction": 0.4,
        "restitution": 0.1,
        "note": "thùng carton có hàng; mật độ khối bao giả định, nên nhập tay",
    },
    "barel": {
        "dynamic": True,
        "mass_kg": 9.0,
        "static_friction": 0.4,
        "dynamic_friction": 0.3,
        "restitution": 0.2,
        "note": "phuy nhựa HDPE rỗng khoảng 8–10 kg",
    },
    "bottle": {
        "dynamic": True,
        "mass_kg": 0.5,
        "static_friction": 0.4,
        "dynamic_friction": 0.3,
        "restitution": 0.3,
        "note": "chai nhựa có nước, giả định",
    },
    "bucket": {
        "dynamic": True,
        "mass_kg": 1.0,
        "static_friction": 0.4,
        "dynamic_friction": 0.3,
        "restitution": 0.2,
        "note": "xô nhựa rỗng, giả định",
    },
    "crate": {
        "dynamic": True,
        "mass_kg": 2.0,
        "static_friction": 0.4,
        "dynamic_friction": 0.3,
        "restitution": 0.2,
        "note": "két nhựa rỗng, giả định",
    },
    "cart": {
        "dynamic": True,
        "mass_kg": 15.0,
        "static_friction": 0.3,
        "dynamic_friction": 0.2,
        "restitution": 0.1,
        "note": "xe đẩy tay, giả định",
    },
    "cone": {
        "dynamic": True,
        "mass_kg": 1.0,
        "static_friction": 0.5,
        "dynamic_friction": 0.4,
        "restitution": 0.2,
        "note": "cọc tiêu nhựa, giả định",
    },
    "fire_extinguisher": {
        "dynamic": True,
        "mass_kg": 9.0,
        "static_friction": 0.4,
        "dynamic_friction": 0.3,
        "restitution": 0.1,
        "note": "bình chữa cháy loại 6 kg, tổng khoảng 9 kg",
    },
}
# Nhãn là kết cấu/trang trí của kho, không phải vật đặt được trong scene (vẫn giữ trong danh mục để
# nhận diện nền): tường, sàn, trần, vạch sơn, biển, giấy, dây, đèn, mã vạch.
NON_PLACEABLE = {
    "wall",
    "floor",
    "ceiling",
    "floor_decal",
    "sign",
    "paper_note",
    "paper_shortcut",
    "wire",
    "lamp",
    "barcode",
    "emergency_board",
    "fuse_box",
}
STATIC_DEFAULT: dict[str, object] = {
    "dynamic": False,
    "static_friction": 0.6,
    "dynamic_friction": 0.5,
    "restitution": 0.1,
    "note": "kết cấu cố định trong kho",
}


def list_keys() -> list[str]:
    """Liệt kê mọi key `.usd` dưới PREFIX (phân trang theo `marker`)."""
    keys: list[str] = []
    marker = ""
    while True:
        query = urllib.parse.urlencode({"prefix": PREFIX, "max-keys": 1000, "marker": marker})
        with urllib.request.urlopen(f"{BUCKET}/?{query}", timeout=60) as response:
            root = ElementTree.fromstring(response.read())
        page = [node.text or "" for node in root.findall("s3:Contents/s3:Key", _NS)]
        keys += [key for key in page if key.endswith(".usd")]
        if (root.findtext("s3:IsTruncated", default="false", namespaces=_NS) != "true") or not page:
            return keys
        marker = page[-1]


def family(name: str) -> str:
    """`SM_CardBoxA_01_1487.usd` → `SM_CardBoxA`: bỏ hậu tố bản sao và biến thể số."""
    stem = name.removesuffix(".usd")
    return re.sub(r"(_\d+)+$", "", stem)


def read_asset(url: str, work: Path) -> dict[str, object]:
    """Tải một asset, đọc nhãn, kích thước bao (mét) và trục lên."""
    local = work / Path(urllib.parse.urlparse(url).path).name
    urllib.request.urlretrieve(url, local)
    stage = Usd.Stage.Open(str(local))
    labels: set[str] = set()
    for prim in stage.Traverse():
        for attribute in prim.GetAttributes():
            name = attribute.GetName()
            if name.endswith("semanticData") or name.startswith("semantics:labels:"):
                value = attribute.Get()
                labels.update([value] if isinstance(value, str) else list(value or []))
    meters = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
    extent = (
        UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
        .ComputeWorldBound(stage.GetPseudoRoot())
        .ComputeAlignedRange()
    )
    size = [round(float(value) * meters, 4) for value in extent.GetSize()]
    return {"labels": sorted(labels), "size_xyz_m": size, "up_axis": str(UsdGeom.GetStageUpAxis(stage))}


def main() -> int:
    """Sinh `object_catalog_v1.json`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    keys = list_keys()
    representatives: dict[str, str] = {}
    for key in sorted(keys, key=len):
        representatives.setdefault(family(Path(key).name), key)
    entries = []
    with tempfile.TemporaryDirectory() as work:
        for name, key in sorted(representatives.items()):
            url = f"{BUCKET}/{key}"
            try:
                info = read_asset(url, Path(work))
            except (OSError, RuntimeError) as error:
                print(f"bỏ qua {name}: {error}", file=sys.stderr)
                continue
            label = next(iter(info["labels"]), None) if info["labels"] else None
            physics = PHYSICS_DEFAULTS.get(str(label), STATIC_DEFAULT) if label else STATIC_DEFAULT
            placeable = label is not None and label not in NON_PLACEABLE
            entries.append(
                {
                    "family": name,
                    "asset_url": url,
                    "semantic_class": label,
                    "placeable": placeable,
                    **info,
                    "physics": physics,
                }
            )
    payload = {
        "catalog": "isaac_simple_warehouse_props",
        "version": 1,
        "source": f"{BUCKET}/{PREFIX}",
        "isaac_version": "5.1",
        "physics_note": "Giá trị vật lý là mặc định tham khảo (asset Isaac không có MassAPI); sửa được trong Studio.",
        "entries": entries,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(entries)} họ asset / {len(keys)} file → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
