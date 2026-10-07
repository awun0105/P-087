"""Trình sinh OpenUSD ASCII (.usda) cho Isaac Sim từ SceneIR.

Xuất cấu trúc scene phân cấp (/World, /World/Environment, /World/Objects)
với metadata chuẩn hóa: metersPerUnit = 1.0, upAxis = "Z" theo OpenReal2Sim và Re3Sim.
"""

import numpy as np

from src.models.contracts.scene import ColliderSpec, ColliderType, SceneIR, SceneObject, SceneObjectState


def _format_prim_name(raw_id: str) -> str:
    """Chuẩn hóa tên Prim hợp lệ trong OpenUSD (chỉ chứa chữ cái, số và dấu gạch dưới)."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in raw_id)


def _generate_ground_plane_usda() -> list[str]:
    """Sinh định nghĩa Prim cho sàn phẳng Analytic Ground Plane."""
    return [
        '        def Cube "GroundPlane" (',
        '            apiSchemas = ["PhysicsCollisionAPI"]',
        "        )",
        "        {",
        "            double size = 1.0",
        "            double3 xformOp:scale = (100.0, 100.0, 0.05)",
        "            double3 xformOp:translate = (0.0, 0.0, -0.025)",
        '            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]',
        "        }",
    ]


def _generate_collider_usda(collider: ColliderSpec) -> list[str]:
    """Sinh định nghĩa Prim cho ColliderSpec dạng hộp; không giả Mesh rỗng."""
    if collider.collider_type not in (ColliderType.AABB, ColliderType.OBB):
        raise ValueError(f"legacy USD exporter cannot preserve collider '{collider.collider_type}'")
    dims = collider.dimensions_xyz_m
    if dims is None or any(not np.isfinite(value) or value <= 0 for value in dims):
        raise ValueError("legacy USD box colliders require finite positive dimensions")
    tx, ty, tz = collider.local_transform.translation_xyz
    qx, qy, qz, qw = collider.local_transform.rotation_quaternion_xyzw

    return [
        '            def Cube "collider" (',
        '                apiSchemas = ["PhysicsCollisionAPI"]',
        "            )",
        "            {",
        "                double size = 1.0",
        f"                double3 xformOp:scale = ({dims[0]}, {dims[1]}, {dims[2]})",
        f"                double3 xformOp:translate = ({tx}, {ty}, {tz})",
        f"                quatf xformOp:orient = ({qw}, {qx}, {qy}, {qz})",
        '                uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:orient", "xformOp:scale"]',
        "            }",
    ]


def _generate_object_usda(obj: SceneObject) -> list[str]:
    """Sinh định nghĩa Prim cho một SceneObject cùng toạ độ và collider."""
    if obj.physics is not None:
        raise ValueError(f"legacy USD exporter cannot preserve ObjectPhysics for '{obj.id}'")
    if obj.asset_ref is not None or isinstance(obj.provenance.get("asset_url"), str):
        raise ValueError(f"legacy USD exporter cannot preserve asset dependencies for '{obj.id}'")
    if obj.state == SceneObjectState.CONFIRMED and obj.collider is None:
        raise ValueError(f"legacy USD exporter requires a collider for confirmed object '{obj.id}'")
    prim_name = _format_prim_name(obj.id)
    tx, ty, tz = obj.transform.translation_xyz
    qx, qy, qz, qw = obj.transform.rotation_quaternion_xyzw

    lines = [
        f'        def Xform "{prim_name}"',
        "        {",
        f"            double3 xformOp:translate = ({tx}, {ty}, {tz})",
        f"            quatf xformOp:orient = ({qw}, {qx}, {qy}, {qz})",
        '            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:orient"]',
    ]

    if obj.collider is not None:
        lines.extend(_generate_collider_usda(obj.collider))

    lines.append("        }")
    return lines


def generate_mesh_layer_usda(vertices: np.ndarray, faces: np.ndarray, prim_name: str = "EnvironmentCollision") -> str:
    """Layer USD chứa một Mesh tĩnh làm collider tam giác (collision mesh môi trường REC-05).

    Toạ độ canonical (mét, Z-up) ghi thẳng, làm tròn 0,1 mm. Collider tĩnh nên dùng
    `physics:approximation = "none"` (triangle mesh, PhysX cho phép với static collider).
    """
    points = ", ".join(f"({x:.4f}, {y:.4f}, {z:.4f})" for x, y, z in np.asarray(vertices, dtype=float))
    indices = ", ".join(str(int(index)) for index in np.asarray(faces).reshape(-1))
    counts = ", ".join("3" for _ in range(len(faces)))
    name = _format_prim_name(prim_name)
    return "\n".join(
        [
            "#usda 1.0",
            "(",
            f'    defaultPrim = "{name}"',
            "    metersPerUnit = 1.0",
            '    upAxis = "Z"',
            ")",
            "",
            f'def Mesh "{name}" (',
            '    prepend apiSchemas = ["PhysicsCollisionAPI", "PhysicsMeshCollisionAPI"]',
            ")",
            "{",
            '    uniform token physics:approximation = "none"',
            '    uniform token subdivisionScheme = "none"',
            f"    int[] faceVertexCounts = [{counts}]",
            f"    int[] faceVertexIndices = [{indices}]",
            f"    point3f[] points = [{points}]",
            "    color3f[] primvars:displayColor = [(0.54, 0.64, 0.78)]",
            "}",
            "",
        ]
    )


def generate_scene_usda(scene: SceneIR, environment_layer: str | None = None) -> str:
    """Chuyển đổi SceneIR thành nội dung văn bản OpenUSD ASCII (.usda) hoàn chỉnh.

    `environment_layer` là đường dẫn tương đối (cùng gói) tới layer mesh collider môi trường;
    None giữ hành vi cũ (chỉ ground plane).
    """
    lines = [
        "#usda 1.0",
        "(",
        "    customLayerData = {",
        '        string creator = "real2sim-candidate-builder-v1.0"',
        f'        string scene_id = "{scene.scene_id}"',
        f'        string scene_revision = "{scene.scene_revision}"',
        "    }",
        '    defaultPrim = "World"',
        "    metersPerUnit = 1.0",
        '    upAxis = "Z"',
        ")",
        "",
        'def Xform "World"',
        "{",
        '    def Xform "Environment"',
        "    {",
    ]

    if scene.environment.collider_ref is not None:
        lines.extend(_generate_ground_plane_usda())
    if environment_layer is not None:
        lines.extend(
            [
                '        def "EnvironmentCollision" (',
                f"            prepend references = @./{environment_layer}@",
                "        )",
                "        {",
                "        }",
            ]
        )

    lines.extend(["    }", "", '    def Xform "Objects"', "    {"])

    for obj in scene.objects:
        if obj.active:
            lines.extend(_generate_object_usda(obj))

    lines.extend(["    }", "}"])
    return "\n".join(lines) + "\n"
