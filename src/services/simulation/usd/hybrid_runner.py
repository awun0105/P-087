"""Xuất USD lai cho Isaac Sim (ADR 0007, chặng 10): Gaussian để hiển thị, collider để va chạm.

Chạy trong runtime có `usd-core` ≥ 26.5 (`data/scene_runtime`); script độc lập (numpy, pxr, trimesh),
không import code app — app ghi `request.json`, đọc `result.json`.

Cấu trúc stage (Z-up, 1 đơn vị = 1 m, 1 kg):

    scene.usda                     stage gốc (không phải .usdz — Isaac lỗi khi thêm asset vào .usdz gốc)
    ├── /World/PhysicsScene
    ├── /World/GroundPlane         collider tĩnh (tuỳ chọn)
    ├── /World/Environment         → environment.usdc: Visual (ParticleField) + Collision (mesh tĩnh)
    └── /World/Objects/<prim>      → objects/<prim>.usdc: Xform (transform của vật)
            ├── Visual             ParticleField3DGaussianSplat trong hệ toạ độ cục bộ của vật
            ├── Collision/part_N   mesh lồi (CoACD) hoặc hộp; approximation convexHull
            └── RigidBody + Mass + Physics Material (vật động) · LabelsAPI:class

Quy ước Gaussian theo 3DGRUT (`threedgrut/export/usd/writers/lightfield.py`, Apache-2.0): opacity sau
sigmoid, scale sau exp, quaternion wxyz, hệ số SH xếp [hệ số][RGB] (PLY xếp theo kênh → chuyển vị).

    <scene_runtime>/bin/python hybrid_runner.py --request request.json --result result.json
"""

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath

import numpy as np
from pxr import Gf, Usd, UsdGeom, UsdPhysics, UsdSemantics, UsdShade, UsdVol, Vt

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from src.services.simulation.mesh_geometry import load_mesh_parts, validate_mesh_arrays

_PLY_TYPES = {"float": "f4", "float32": "f4", "double": "f8", "uchar": "u1", "int": "i4", "uint": "u4"}


def read_gaussian_ply(path: Path) -> dict[str, np.ndarray]:
    """Đọc PLY 3DGS nhị phân (quy ước Inria/Brush) → mảng thuộc tính theo tên."""
    with path.open("rb") as handle:
        header: list[str] = []
        while (line := handle.readline().decode("ascii").strip()) != "end_header":
            header.append(line)
        if "format binary_little_endian 1.0" not in header:
            raise ValueError(f"{path.name}: chỉ hỗ trợ PLY binary_little_endian")
        count = next(int(item.split()[2]) for item in header if item.startswith("element vertex"))
        fields = [
            (item.split()[2], "<" + _PLY_TYPES[item.split()[1]]) for item in header if item.startswith("property")
        ]
        data = np.fromfile(handle, dtype=np.dtype(fields), count=count)
    return {name: np.asarray(data[name]) for name, _ in fields}


def gaussian_arrays(ply: dict[str, np.ndarray]) -> dict[str, np.ndarray | int]:
    """Chuyển thuộc tính PLY (trước kích hoạt) sang giá trị ParticleField (sau kích hoạt)."""
    positions = np.stack([ply["x"], ply["y"], ply["z"]], axis=1).astype(np.float32)
    rotations = np.stack([ply[f"rot_{i}"] for i in range(4)], axis=1).astype(np.float64)  # wxyz
    norms = np.linalg.norm(rotations, axis=1, keepdims=True)
    rotations = rotations / np.where(norms > 0, norms, 1.0)
    scales = np.exp(np.stack([ply[f"scale_{i}"] for i in range(3)], axis=1)).astype(np.float32)
    opacities = (1.0 / (1.0 + np.exp(-ply["opacity"].astype(np.float64)))).astype(np.float32)
    dc = np.stack([ply[f"f_dc_{i}"] for i in range(3)], axis=1).astype(np.float32)
    rest_names = sorted((name for name in ply if name.startswith("f_rest_")), key=lambda name: int(name[7:]))
    rest_per_channel = len(rest_names) // 3
    degree = int(round(np.sqrt(rest_per_channel + 1))) - 1 if rest_per_channel else 0
    if rest_per_channel:
        rest = np.stack([ply[name] for name in rest_names], axis=1).astype(np.float32)
        rest = rest.reshape(len(positions), 3, rest_per_channel).transpose(0, 2, 1)  # [N][hệ số][RGB]
        coefficients = np.concatenate([dc[:, None, :], rest], axis=1)
    else:
        coefficients = dc[:, None, :]
    return {
        "positions": positions,
        "rotations": rotations,
        "scales": scales,
        "opacities": opacities,
        "coefficients": coefficients.reshape(-1, 3),
        "degree": degree,
        "per_particle": coefficients.shape[1],
    }


def merged_gaussians(base: Path | None, extras: list[dict]) -> dict[str, np.ndarray | int] | None:
    """Gaussian nền + Gaussian của các vật không xuất riêng (ứng viên chưa xác nhận), dời về world.

    Mọi file cùng nguồn 3DGS nên cùng bậc SH; khác bậc là lỗi dữ liệu, không tự cắt/đệm.
    """
    parts = [gaussian_arrays(read_gaussian_ply(base))] if base else []
    for extra in extras:
        arrays = gaussian_arrays(read_gaussian_ply(Path(extra["ply"])))
        arrays["positions"] = np.asarray(arrays["positions"]) + np.asarray(extra["translation"], dtype=np.float32)
        parts.append(arrays)
    if not parts:
        return None
    if len({int(part["per_particle"]) for part in parts}) != 1:
        raise ValueError("các file Gaussian khác bậc SH, không gộp được")
    merged: dict[str, np.ndarray | int] = {"degree": parts[0]["degree"], "per_particle": parts[0]["per_particle"]}
    for key in ("positions", "rotations", "scales", "opacities", "coefficients"):
        merged[key] = np.concatenate([np.asarray(part[key]) for part in parts])
    return merged


def write_particle_field(stage: Usd.Stage, path: str, gaussians: dict[str, np.ndarray | int]) -> int:
    """Ghi Gaussian vào `UsdVol.ParticleField3DGaussianSplat`; trả số Gaussian."""
    field = UsdVol.ParticleField3DGaussianSplat.Define(stage, path)
    positions = np.asarray(gaussians["positions"])
    field.CreatePositionsAttr().Set(Vt.Vec3fArray.FromNumpy(positions))
    rotations = np.asarray(gaussians["rotations"])
    field.CreateOrientationsAttr().Set(Vt.QuatfArray([Gf.Quatf(*map(float, q)) for q in rotations]))
    field.CreateScalesAttr().Set(Vt.Vec3fArray.FromNumpy(np.asarray(gaussians["scales"])))
    field.CreateOpacitiesAttr().Set(Vt.FloatArray.FromNumpy(np.asarray(gaussians["opacities"])))
    field.CreateRadianceSphericalHarmonicsDegreeAttr().Set(int(gaussians["degree"]))
    coefficients = field.CreateRadianceSphericalHarmonicsCoefficientsAttr()
    coefficients.Set(Vt.Vec3fArray.FromNumpy(np.asarray(gaussians["coefficients"], dtype=np.float32)))
    coefficients.SetMetadata("elementSize", int(gaussians["per_particle"]))
    if len(positions):
        low, high = positions.min(axis=0), positions.max(axis=0)
        field.CreateExtentAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*map(float, low)), Gf.Vec3f(*map(float, high))]))
    return len(positions)


def load_mesh(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Mesh tam giác (đỉnh, mặt) từ GLB/PLY/OBJ; gộp mọi node của GLB."""
    parts = load_mesh_parts(path)
    vertices, faces = [], []
    offset = 0
    for points, triangles in parts:
        vertices.append(points)
        faces.append(triangles + offset)
        offset += len(points)
    return validate_mesh_arrays(np.concatenate(vertices), np.concatenate(faces))


def load_parts(path: Path) -> list[tuple[np.ndarray, np.ndarray]]:
    """Các khối lồi trong một collider; giữ node transforms và thứ tự ổn định."""
    return load_mesh_parts(path)


def write_mesh(stage: Usd.Stage, path: str, vertices: np.ndarray, faces: np.ndarray, approximation: str) -> None:
    """Mesh collider (không hiển thị) với CollisionAPI + MeshCollisionAPI."""
    vertices, faces = validate_mesh_arrays(vertices, faces)
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr().Set(Vt.Vec3fArray.FromNumpy(vertices))
    mesh.CreateFaceVertexCountsAttr().Set(Vt.IntArray.FromNumpy(np.full(len(faces), 3, dtype=np.int32)))
    mesh.CreateFaceVertexIndicesAttr().Set(Vt.IntArray.FromNumpy(faces.reshape(-1)))
    mesh.CreatePurposeAttr().Set(UsdGeom.Tokens.guide)
    UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
    UsdPhysics.MeshCollisionAPI.Apply(mesh.GetPrim()).CreateApproximationAttr().Set(approximation)


def write_box_collider(stage: Usd.Stage, path: str, dims: list[float]) -> None:
    """Collider hộp khi vật chưa có mesh (vật cản người dùng thêm)."""
    if len(dims) != 3 or any(not math.isfinite(float(value)) or float(value) <= 0 for value in dims):
        raise ValueError("box collider requires three finite positive dimensions")
    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr().Set(1.0)
    cube.AddScaleOp().Set(Gf.Vec3f(*map(float, dims)))
    cube.CreatePurposeAttr().Set(UsdGeom.Tokens.guide)
    UsdPhysics.CollisionAPI.Apply(cube.GetPrim())


def apply_physics(stage: Usd.Stage, prim: Usd.Prim, physics: dict | None) -> None:
    """Author only the mass and material values present in ObjectPhysics."""
    if physics is None:
        return
    if not isinstance(physics, dict) or not isinstance(physics.get("dynamic"), bool):
        raise ValueError("ObjectPhysics must declare a boolean dynamic field")
    for key in ("static_friction", "dynamic_friction", "restitution"):
        value = physics.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value)):
            raise ValueError(f"ObjectPhysics requires finite {key}")
        if float(value) < 0 or (key == "restitution" and float(value) > 1):
            raise ValueError(f"ObjectPhysics {key} is outside its contract range")
    mass = physics.get("mass_kg")
    if mass is not None and (
        isinstance(mass, bool) or not isinstance(mass, int | float) or not math.isfinite(float(mass)) or mass <= 0
    ):
        raise ValueError("ObjectPhysics mass_kg must be finite and positive when present")
    density = physics.get("density_kg_m3")
    if density is not None and (
        isinstance(density, bool)
        or not isinstance(density, int | float)
        or not math.isfinite(float(density))
        or density <= 0
    ):
        raise ValueError("ObjectPhysics density_kg_m3 must be finite and positive when present")
    mass_source = physics.get("mass_source")
    if physics["dynamic"] and (mass is None or not isinstance(mass_source, str) or not mass_source):
        raise ValueError("dynamic ObjectPhysics requires mass_kg and mass_source")
    provenance = physics.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("ObjectPhysics provenance must be an object")
    if physics["dynamic"]:
        UsdPhysics.RigidBodyAPI.Apply(prim)
    if mass is not None or density is not None:
        mass_api = UsdPhysics.MassAPI.Apply(prim)
        if mass is not None:
            mass_api.CreateMassAttr().Set(float(mass))
        if density is not None:
            mass_api.CreateDensityAttr().Set(float(density))
    material = UsdShade.Material.Define(stage, prim.GetPath().AppendChild("PhysicsMaterial"))
    api = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    api.CreateStaticFrictionAttr().Set(float(physics["static_friction"]))
    api.CreateDynamicFrictionAttr().Set(float(physics["dynamic_friction"]))
    api.CreateRestitutionAttr().Set(float(physics["restitution"]))
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material, UsdShade.Tokens.weakerThanDescendants, "physics")
    metadata = {
        key: physics[key]
        for key in (
            "dynamic",
            "mass_kg",
            "mass_source",
            "density_kg_m3",
            "static_friction",
            "dynamic_friction",
            "restitution",
            "provenance",
        )
        if physics.get(key) is not None
    }
    prim.SetCustomDataByKey("real2sim", {"physics": metadata})


def _collider_transform(stage: Usd.Stage, path: str, collider: dict) -> None:
    local = collider.get("local_transform")
    if not isinstance(local, dict):
        raise ValueError("collider local_transform is required")
    translation = local.get("translation_xyz")
    rotation = local.get("rotation_quaternion_xyzw")
    if (
        not isinstance(translation, list | tuple)
        or len(translation) != 3
        or any(
            isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value))
            for value in translation
        )
        or not isinstance(rotation, list | tuple)
        or len(rotation) != 4
        or any(
            isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(float(value))
            for value in rotation
        )
    ):
        raise ValueError("collider local_transform must contain finite translation and quaternion values")
    qx, qy, qz, qw = map(float, rotation)
    if not math.isclose(math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw), 1.0, rel_tol=1e-5, abs_tol=1e-5):
        raise ValueError("collider local_transform quaternion must be normalized")
    frame = UsdGeom.Xform.Define(stage, path)
    frame.AddTranslateOp().Set(Gf.Vec3d(*map(float, translation)))
    frame.AddOrientOp().Set(Gf.Quatf(qw, qx, qy, qz))


def _copy_asset(item: dict, output_dir: Path) -> str | None:
    source_value = item.get("asset_source_path")
    if source_value is None:
        return None
    source = Path(source_value)
    relative = PurePosixPath(item.get("asset_package_path", ""))
    checksum = item.get("asset_checksum")
    if (
        not source.is_file()
        or relative.is_absolute()
        or len(relative.parts) != 2
        or relative.parts[0] != "assets"
        or any(part in {"", ".", ".."} for part in relative.parts)
        or source.suffix.lower() not in {".usd", ".usda", ".usdc", ".usdz"}
        or source.suffix.lower() != Path(relative.name).suffix.lower()
        or not isinstance(checksum, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", checksum) is None
        or relative.name != checksum.removeprefix("sha256:") + source.suffix.lower()
    ):
        raise ValueError("USD asset path or checksum is outside the package contract")
    destination = output_dir.joinpath(*relative.parts)
    if not destination.resolve().is_relative_to(output_dir.resolve()):
        raise ValueError("USD asset path escapes the package root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    try:
        with source.open("rb") as input_stream, destination.open("wb") as output_stream:
            for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                digest.update(chunk)
                output_stream.write(chunk)
    except OSError as error:
        destination.unlink(missing_ok=True)
        raise ValueError("USD asset bytes could not be copied into the package") from error
    if "sha256:" + digest.hexdigest() != checksum:
        destination.unlink(missing_ok=True)
        raise ValueError("USD asset bytes do not match the declared checksum")
    return relative.as_posix()


def _validate_stage_closure(scene_path: Path, package_root: Path) -> None:
    stage = Usd.Stage.Open(str(scene_path))
    if stage is None:
        raise ValueError("generated USD entrypoint cannot be opened")
    if stage.GetCompositionErrors():
        raise ValueError("generated USD entrypoint has unresolved composition dependencies")
    root = package_root.resolve()
    for layer in stage.GetUsedLayers():
        if layer.anonymous:
            continue
        real_path = layer.realPath
        if not real_path:
            raise ValueError("generated USD entrypoint contains a non-file dependency")
        packaged_path = Path(real_path.split("[", 1)[0]).resolve()
        if not packaged_path.is_relative_to(root) or not packaged_path.is_file():
            raise ValueError("generated USD entrypoint references bytes outside the package")


def label(prim: Usd.Prim, semantic_class: str | None) -> None:
    """Nhãn lớp cho Replicator/annotator (`UsdSemantics.LabelsAPI`, Isaac ≥ 5.0)."""
    if semantic_class:
        UsdSemantics.LabelsAPI.Apply(prim, "class").CreateLabelsAttr().Set([semantic_class])


def new_layer(path: Path) -> Usd.Stage:
    """Stage con Z-up, mét, kg; prim mặc định `/Root`."""
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdPhysics.SetStageKilogramsPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/Root")
    stage.SetDefaultPrim(root.GetPrim())
    return stage


def probe_runtime() -> dict:
    """Exercise every USD schema/API used by the hybrid writer in an in-memory stage."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdPhysics.SetStageKilogramsPerUnit(stage, 1.0)
    mesh = UsdGeom.Mesh.Define(stage, "/Probe/Collision")
    UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
    UsdPhysics.MeshCollisionAPI.Apply(mesh.GetPrim()).CreateApproximationAttr().Set(UsdPhysics.Tokens.none)
    body = UsdGeom.Xform.Define(stage, "/Probe/Body").GetPrim()
    UsdPhysics.RigidBodyAPI.Apply(body)
    UsdPhysics.MassAPI.Apply(body).CreateMassAttr().Set(1.0)
    frame = UsdGeom.Xform.Define(stage, "/Probe/ColliderFrame")
    frame.AddTranslateOp().Set(Gf.Vec3d(0.1, 0.2, 0.3))
    frame.AddOrientOp().Set(Gf.Quatf(1.0, 0.0, 0.0, 0.0))
    body.SetCustomDataByKey("real2sim", {"physics": {"dynamic": True, "mass_source": "probe"}})
    material = UsdShade.Material.Define(stage, "/Probe/Material")
    physics_material = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics_material.CreateStaticFrictionAttr().Set(0.5)
    physics_material.CreateDynamicFrictionAttr().Set(0.4)
    physics_material.CreateRestitutionAttr().Set(0.0)
    UsdShade.MaterialBindingAPI.Apply(body).Bind(material, UsdShade.Tokens.weakerThanDescendants, "physics")
    UsdSemantics.LabelsAPI.Apply(body, "class").CreateLabelsAttr().Set(["probe"])
    field = UsdVol.ParticleField3DGaussianSplat.Define(stage, "/Probe/Visual")
    field.CreatePositionsAttr().Set(Vt.Vec3fArray())
    stage.GetRootLayer().ExportToString()
    return {
        "qualified": True,
        "usd_version": ".".join(str(part) for part in Usd.GetVersion()),
        "capabilities": [
            "triangle_mesh_collision",
            "convex_mesh_collision",
            "rigid_body_mass",
            "physics_material",
            "collider_local_transform",
            "physics_source_metadata",
            "semantic_labels",
            "gaussian_particle_field",
            "meters_z_up",
        ],
    }


def build(request: dict) -> dict:
    """Dựng toàn bộ stage; trả tóm tắt số Gaussian/collider để app ghi vào provenance."""
    out = Path(request["output_dir"])
    (out / "objects").mkdir(parents=True, exist_ok=True)
    summary: dict = {"environment_gaussians": 0, "objects": [], "external_assets": []}

    env = request.get("environment") or {}
    env_stage = new_layer(out / "environment.usdc")
    environment_gaussians = merged_gaussians(
        Path(env["gaussians_ply"]) if env.get("gaussians_ply") else None, env.get("extra_gaussians") or []
    )
    if environment_gaussians is not None:
        summary["environment_gaussians"] = write_particle_field(env_stage, "/Root/Visual", environment_gaussians)
    if env.get("collision_mesh"):
        vertices, faces = load_mesh(Path(env["collision_mesh"]))
        write_mesh(env_stage, "/Root/Collision", vertices, faces, UsdPhysics.Tokens.none)
        summary["environment_triangles"] = int(len(faces))
    env_stage.GetRootLayer().Save()

    root = Usd.Stage.CreateNew(str(out / "scene.usda"))
    UsdGeom.SetStageUpAxis(root, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(root, 1.0)
    UsdPhysics.SetStageKilogramsPerUnit(root, 1.0)
    world = UsdGeom.Xform.Define(root, "/World")
    root.SetDefaultPrim(world.GetPrim())
    UsdPhysics.Scene.Define(root, "/World/PhysicsScene")
    if request.get("ground_plane", True):
        write_box_collider(root, "/World/GroundPlane", [200.0, 200.0, 0.02])
        UsdGeom.Xformable(root.GetPrimAtPath("/World/GroundPlane")).AddTranslateOp().Set(Gf.Vec3d(0, 0, -0.01))
    UsdGeom.Xform.Define(root, "/World/Environment").GetPrim().GetReferences().AddReference("./environment.usdc")
    UsdGeom.Scope.Define(root, "/World/Objects")

    for item in request.get("objects", []):
        prim_name = item["prim"]
        layer_path = out / "objects" / f"{prim_name}.usdc"
        stage = new_layer(layer_path)
        prim = stage.GetPrimAtPath("/Root")
        collider = item.get("collider")
        if not isinstance(collider, dict):
            raise ValueError(f"confirmed object '{prim_name}' requires an explicit collider")
        collider_type = collider.get("type")
        if collider_type not in {"AABB", "OBB", "CONVEX_DECOMPOSITION"}:
            raise ValueError(f"unsupported collider type for '{prim_name}'")
        entry = {"prim": prim_name, "gaussians": 0, "collider_type": collider_type, "collision_parts": 0}
        if item.get("gaussians_ply"):
            entry["gaussians"] = write_particle_field(
                stage, "/Root/Visual", gaussian_arrays(read_gaussian_ply(Path(item["gaussians_ply"])))
            )
        asset_package_path = _copy_asset(item, out)
        if asset_package_path is not None:
            asset = UsdGeom.Xform.Define(stage, "/Root/Asset")
            relative_reference = "../" + asset_package_path
            asset.GetPrim().GetReferences().AddReference(relative_reference)
            entry["asset"] = asset_package_path
            summary["external_assets"].append(
                {"prim": prim_name, "path": asset_package_path, "checksum": item["asset_checksum"]}
            )
        _collider_transform(stage, "/Root/Collision", collider)
        if collider_type in {"AABB", "OBB"}:
            if collider.get("geometry_path") or collider.get("part_paths"):
                raise ValueError(f"box collider for '{prim_name}' cannot also declare mesh geometry")
            dimensions = collider.get("dimensions_xyz_m")
            if not isinstance(dimensions, list | tuple):
                raise ValueError(f"box collider for '{prim_name}' requires collider dimensions")
            write_box_collider(stage, "/Root/Collision/box", list(dimensions))
            entry["collision_parts"] = 1
            entry["collider_dimensions_xyz_m"] = list(dimensions)
        else:
            if collider.get("dimensions_xyz_m") is not None:
                raise ValueError(f"convex collider for '{prim_name}' cannot declare box dimensions")
            parts = [load_mesh(Path(part)) for part in collider.get("part_paths") or []]
            if collider.get("geometry_path"):
                parts += load_parts(Path(collider["geometry_path"]))
            if not parts:
                raise ValueError(f"convex collider for '{prim_name}' requires at least one valid mesh part")
            for index, (vertices, faces) in enumerate(parts):
                write_mesh(stage, f"/Root/Collision/part_{index:03d}", vertices, faces, UsdPhysics.Tokens.convexHull)
                entry["collision_parts"] += 1
        entry["collider_local_transform"] = collider["local_transform"]
        physics = item.get("physics")
        apply_physics(stage, prim, item.get("physics"))
        if physics is not None:
            entry["physics"] = {
                key: physics.get(key)
                for key in (
                    "dynamic",
                    "mass_kg",
                    "mass_source",
                    "density_kg_m3",
                    "static_friction",
                    "dynamic_friction",
                    "restitution",
                )
            }
        label(prim, item.get("semantic_class"))
        stage.GetRootLayer().Save()

        placed = UsdGeom.Xform.Define(root, f"/World/Objects/{prim_name}")
        placed.GetPrim().GetReferences().AddReference(f"./objects/{prim_name}.usdc")
        tx, ty, tz = item["translation"]
        qx, qy, qz, qw = item["rotation_xyzw"]
        placed.AddTranslateOp().Set(Gf.Vec3d(tx, ty, tz))
        placed.AddOrientOp().Set(Gf.Quatf(float(qw), float(qx), float(qy), float(qz)))
        if item.get("name"):
            placed.GetPrim().SetDisplayName(str(item["name"]))
        summary["objects"].append(entry)

    root.GetRootLayer().Save()
    _validate_stage_closure(out / "scene.usda", out)
    summary["root"] = "scene.usda"
    summary["usd_version"] = ".".join(str(part) for part in Usd.GetVersion())
    return summary


def main() -> int:
    """CLI: request JSON → stage USD + result JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.probe:
        result = probe_runtime()
    else:
        if args.request is None:
            parser.error("--request is required unless --probe is specified")
        result = build(json.loads(args.request.read_text(encoding="utf-8")))
    args.result.write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
