"""Dựng hình xem trước trên web cho danh mục vật thể từ mô hình CC0 hoặc hình khối tự dựng (ADR 0010 mục 3).

Mỗi họ asset đặt được trong `configs/product/object_catalog_v1.json` nhận một GLB ở
`configs/product/catalog_previews/<family>.glb`: mét, trục Z lên, tâm hộp bao tại gốc, co giãn theo từng trục về đúng
`size_xyz_m` của họ asset — khớp hộp collider mà SceneIR lưu cho vật thêm từ thư viện. Họ asset vẫn trỏ tới đúng USD
của NVIDIA để xuất gói Isaac; file ở đây chỉ để trình duyệt vẽ, không dùng tới asset nào của NVIDIA.

Nguồn theo `configs/product/catalog_previews_cc0.json`: `cc0` = tải theo URL đã ghim và kiểm sha256; `procedural` =
dựng bằng hình khối trong script này. Chạy lại cho ra cùng file với cùng nguồn.

    python -m scripts.scene.build_cc0_previews [--cache data/cc0_cache]
"""

import argparse
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "configs/product/object_catalog_v1.json"
MANIFEST = ROOT / "configs/product/catalog_previews_cc0.json"
OUT = ROOT / "configs/product/catalog_previews"
#: glTF là Y lên; xoay +90° quanh X để thành Z lên của hệ canonical.
Y_UP_TO_Z_UP = trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])

RED, ORANGE, BLUE, STEEL, CONCRETE, BLACK, CARDBOARD = (
    (196, 32, 36, 255),
    (226, 113, 29, 255),
    (43, 94, 167, 255),
    (140, 146, 156, 255),
    (170, 168, 160, 255),
    (30, 30, 30, 255),
    (190, 150, 100, 255),
)


def _part(mesh: trimesh.Trimesh, color: tuple[int, int, int, int]) -> trimesh.Trimesh:
    mesh.visual.face_colors = color
    return mesh


def _box(size: tuple[float, float, float], center: tuple[float, float, float], color: tuple) -> trimesh.Trimesh:
    return _part(
        trimesh.creation.box(extents=size, transform=trimesh.transformations.translation_matrix(center)), color
    )


def _cylinder(radius: float, height: float, center: tuple[float, float, float], color: tuple, axis: str = "z"):  # noqa: ANN202
    mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=24)
    if axis == "x":
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    mesh.apply_translation(center)
    return _part(mesh, color)


def procedural(shape: str) -> trimesh.Scene:
    """Hình khối trong hộp đơn vị [-0,5; 0,5]³ (Z lên); bước co giãn sau đó đưa về kích thước thật."""
    parts: list[trimesh.Trimesh]
    if shape == "box":
        parts = [_box((1, 1, 1), (0, 0, 0), CARDBOARD)]
    elif shape == "beam":
        parts = [_box((1, 1, 1), (0, 0, 0), ORANGE)]
    elif shape == "column":
        parts = [_box((1, 1, 1), (0, 0, 0), CONCRETE)]
    elif shape == "rack_frame":
        # Khung đứng của giá kệ: hai cột hai bên theo Y, các thanh giằng ngang.
        parts = [_box((1, 0.12, 1), (0, y, 0), BLUE) for y in (-0.44, 0.44)]
        parts += [_box((0.6, 0.88, 0.02), (0, 0, z), BLUE) for z in (-0.35, -0.05, 0.25)]
    elif shape == "rack_shelf":
        # Tầng kệ: hai xà dọc trước/sau và mặt sàn mỏng.
        parts = [_box((1, 0.1, 0.35), (0, y, 0.3), ORANGE) for y in (-0.45, 0.45)]
        parts.append(_box((1, 0.8, 0.08), (0, 0, 0.42), STEEL))
    elif shape == "cart":
        # Xe đẩy sàn thấp: mặt sàn và bốn bánh.
        parts = [_box((1, 1, 0.35), (0, 0, 0.2), BLUE)]
        parts += [_cylinder(0.18, 0.12, (x, y, -0.3), BLACK, axis="x") for x in (-0.38, 0.38) for y in (-0.4, 0.4)]
    elif shape == "fire_extinguisher":
        # Bình chữa cháy: thân trụ đỏ, đầu tròn, cổ và vòi đen.
        parts = [
            _cylinder(0.42, 0.7, (0, 0, -0.15), RED),
            _part(trimesh.creation.icosphere(subdivisions=2, radius=0.42).apply_translation((0, 0, 0.2)), RED),
            _cylinder(0.1, 0.15, (0, 0, 0.42), BLACK),
            _box((0.08, 0.5, 0.08), (0, 0.22, 0.4), BLACK),
        ]
    else:
        raise ValueError(f"hình khối không có: {shape}")
    return trimesh.Scene(parts)


def cc0(source: dict, cache: Path) -> trimesh.Scene:
    """Mô hình CC0 theo URL đã ghim; sai sha256 thì dừng (nguồn đã đổi, phải xem lại giấy phép và hình)."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{source['sha256']}.glb"
    if not path.is_file():
        # Máy chủ của poly.pizza từ chối request không có User-Agent.
        request = urllib.request.Request(source["url"], headers={"User-Agent": "real2sim-catalog-previews"})
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - URL ghim trong cấu hình
            path.write_bytes(response.read())
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != source["sha256"]:
        path.unlink()
        raise ValueError(f"sha256 của {source['url']} không khớp")
    scene = trimesh.load(io.BytesIO(payload), file_type="glb", force="scene")
    scene.apply_transform(Y_UP_TO_Z_UP)
    return scene


def fit(scene: trimesh.Scene, size: tuple[float, float, float]) -> trimesh.Scene:
    """Xoay 90° quanh Z nếu chiều dài ngang của mô hình ngược với họ asset, co giãn từng trục về `size`, tâm về gốc."""
    extents = scene.extents
    if (extents[0] - extents[1]) * (size[0] - size[1]) < 0:
        scene.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))
    low, high = scene.bounds
    center = (low + high) / 2
    scale = np.asarray(size, dtype=float) / np.maximum(high - low, 1e-9)
    matrix = np.diag([*scale, 1.0]) @ trimesh.transformations.translation_matrix(-center)
    scene.apply_transform(matrix)
    # Ghi toạ độ đã biến đổi thẳng vào đỉnh (không để trong transform của node): mọi nơi đọc đỉnh thô của GLB, kể cả
    # phép kiểm kích thước, thấy đúng hình như trình duyệt vẽ.
    # Tên node của trimesh có hậu tố ngẫu nhiên: duyệt theo tên lưới và đặt tên cố định để file ra giống hệt nhau
    # giữa các lần chạy.
    instances = sorted(
        ((scene.graph[node][1], node) for node in scene.graph.nodes_geometry),
        key=lambda item: (item[0], tuple(scene.graph[item[1]][0].ravel())),
    )
    baked = {}
    for index, (geometry, node) in enumerate(instances):
        mesh = scene.geometry[geometry].copy()
        mesh.apply_transform(scene.graph[node][0])
        baked[f"part_{index:02d}"] = mesh
    return trimesh.Scene(baked)


def source_for(family: str, semantic_class: str | None, manifest: dict) -> dict:
    """Nguồn hình của một họ asset: khai riêng theo họ trước, rồi theo nhãn lớp."""
    source = manifest["families"].get(family) or manifest["classes"].get(semantic_class or "")
    if source is None:
        raise ValueError(f"{family} ({semantic_class}) chưa có nguồn hình trong {MANIFEST.name}")
    return source


def main(argv: list[str] | None = None) -> int:
    """Dựng lại toàn bộ hình xem trước và bảng chỉ mục; trả exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=ROOT / "data/cc0_cache")
    args = parser.parse_args(argv)
    catalog = json.loads(CATALOG.read_text())
    manifest = json.loads(MANIFEST.read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    index = {}
    try:
        for entry in (item for item in catalog["entries"] if item["placeable"]):
            source = source_for(entry["family"], entry.get("semantic_class"), manifest)
            scene = cc0(source, args.cache) if source["kind"] == "cc0" else procedural(source["shape"])
            payload = fit(scene, tuple(entry["size_xyz_m"])).export(file_type="glb")
            (OUT / f"{entry['family']}.glb").write_bytes(payload)
            index[entry["family"]] = {
                "kind": source["kind"],
                "source": source.get("page") or source.get("shape"),
                "size_xyz_m": entry["size_xyz_m"],
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
    except (OSError, ValueError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    (OUT / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(index)} hình xem trước → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
