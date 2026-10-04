"""Dựng bản xem trước GLB cho asset Isaac trong danh mục, để Studio vẽ hình khối thật thay cho hộp.

Chạy trong runtime có `usd-core` + `trimesh` (`data/scene_runtime`), cần mạng. Mỗi asset đặt được trong
`configs/product/object_catalog_v1.json` → `<out>/<family>.glb`:

    data/scene_runtime/bin/python scripts/scene/build_asset_previews.py --out data/asset_previews

GLB chỉ có **hình khối** (lưới tam giác gộp, màu `displayColor` nếu asset có, không texture/MDL), đã đổi về
mét, trục Z lên, và dời tâm hộp bao về gốc — khớp với hộp collider mà SceneIR lưu cho vật thêm từ thư viện.
Đây là bản xem trên web; USD xuất cho Isaac vẫn tham chiếu asset gốc. File sinh ra không commit vào repo
(asset thuộc NVIDIA): mỗi máy chạy script một lần, API phục vụ từ `PRODUCT_ASSET_PREVIEW_DIR`.
"""

import argparse
import json
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import trimesh
from pxr import Usd, UsdGeom

CATALOG = Path(__file__).resolve().parents[2] / "configs/product/object_catalog_v1.json"
_GREY = (170, 170, 170, 255)


def _triangles(counts: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Tam giác hoá kiểu quạt cho mặt n cạnh."""
    faces, cursor = [], 0
    for count in counts:
        for step in range(1, count - 1):
            faces.append((indices[cursor], indices[cursor + step], indices[cursor + step + 1]))
        cursor += count
    return np.array(faces, dtype=np.int64).reshape(-1, 3)


def _color(mesh: UsdGeom.Mesh) -> tuple[int, int, int, int]:
    values = mesh.GetDisplayColorAttr().Get()
    if not values:
        return _GREY
    red, green, blue = (int(round(min(max(float(channel), 0.0), 1.0) * 255)) for channel in values[0])
    return (red, green, blue, 255)


def asset_mesh(path: Path) -> trimesh.Trimesh:
    """Gộp mọi lưới của một file USD thành một lưới: mét, Z lên, tâm hộp bao tại gốc."""
    stage = Usd.Stage.Open(str(path))
    meters = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    parts = []
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdGeom.Mesh) or UsdGeom.Imageable(prim).ComputePurpose() == UsdGeom.Tokens.guide:
            continue
        mesh = UsdGeom.Mesh(prim)
        points, counts, indices = (
            mesh.GetPointsAttr().Get(),
            mesh.GetFaceVertexCountsAttr().Get(),
            mesh.GetFaceVertexIndicesAttr().Get(),
        )
        if not points or not counts or not indices:
            continue
        matrix = np.array(cache.GetLocalToWorldTransform(prim))  # USD: vector hàng × ma trận
        vertices = np.c_[np.array(points, dtype=np.float64), np.ones(len(points))] @ matrix
        faces = _triangles(np.array(counts), np.array(indices))
        if len(faces):
            part = trimesh.Trimesh(vertices[:, :3] * meters, faces, process=False)
            part.visual.vertex_colors = np.tile(_color(mesh), (len(part.vertices), 1))
            parts.append(part)
    if not parts:
        raise ValueError("asset không có lưới nào")
    merged = trimesh.util.concatenate(parts)
    if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y:
        merged.vertices = merged.vertices[:, [0, 2, 1]] * np.array([1.0, -1.0, 1.0])  # Y lên → Z lên
    merged.vertices -= merged.bounds.mean(axis=0)
    return merged


def main() -> int:
    """Sinh GLB cho mọi asset đặt được; trả 1 nếu có asset lỗi."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", nargs="*", help="chỉ dựng các family này (mặc định: mọi asset đặt được)")
    args = parser.parse_args()
    entries = [item for item in json.loads(CATALOG.read_text(encoding="utf-8"))["entries"] if item["placeable"]]
    if args.only:
        entries = [item for item in entries if item["family"] in set(args.only)]
    args.out.mkdir(parents=True, exist_ok=True)
    failed = 0
    with tempfile.TemporaryDirectory() as work:
        for entry in entries:
            target = args.out / f"{entry['family']}.glb"
            local = Path(work) / Path(urllib.parse.urlparse(entry["asset_url"]).path).name
            try:
                urllib.request.urlretrieve(entry["asset_url"], local)
                mesh = asset_mesh(local)
                target.write_bytes(mesh.export(file_type="glb"))
            except (OSError, RuntimeError, ValueError) as error:
                failed += 1
                print(f"[!] {entry['family']}: {error}", file=sys.stderr)
                continue
            size = " × ".join(f"{value:.2f}" for value in mesh.extents)
            print(f"{entry['family']}: {len(mesh.faces)} tam giác, {size} m (danh mục {entry['size_xyz_m']})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
