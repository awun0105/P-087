"""Trình sinh OpenUSD ASCII (.usda) cho Isaac Sim từ SceneIR.

Xuất cấu trúc scene phân cấp (/World, /World/Environment, /World/Objects)
với metadata chuẩn hóa: metersPerUnit = 1.0, upAxis = "Z" theo OpenReal2Sim và Re3Sim.
"""

from src.models.contracts.scene import ColliderSpec, ColliderType, SceneIR, SceneObject


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
    """Sinh định nghĩa Prim cho ColliderSpec dạng Box."""
    dims = collider.dimensions_xyz_m or (1.0, 1.0, 1.0)
    tx, ty, tz = collider.local_transform.translation_xyz
    qx, qy, qz, qw = collider.local_transform.rotation_quaternion_xyzw

    prim_type = "Cube" if collider.collider_type in (ColliderType.AABB, ColliderType.OBB) else "Mesh"
    return [
        f'            def {prim_type} "collider" (',
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


def generate_scene_usda(scene: SceneIR) -> str:
    """Chuyển đổi SceneIR thành nội dung văn bản OpenUSD ASCII (.usda) hoàn chỉnh."""
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

    lines.extend(["    }", "", '    def Xform "Objects"', "    {"])

    for obj in scene.objects:
        if obj.active:
            lines.extend(_generate_object_usda(obj))

    lines.extend(["    }", "}"])
    return "\n".join(lines) + "\n"

