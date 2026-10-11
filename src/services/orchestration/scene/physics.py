"""Vùng gốc của các vật động trong lưới va chạm chung của scene (ADR 0010, H5).

Lưới va chạm của scene (REC-05) dựng từ cả scene 3DGS nên vẫn chứa hình của mọi vật đã tách. Muốn đẩy được một vật
trong trình duyệt thì vùng của nó phải được khoét khỏi lưới tĩnh — nếu không, người đi bị chính bản sao tĩnh của vật
chặn lại và vật bị kẹt trong đó. Vùng cần khoét là chỗ vật **đứng lúc dựng lại scene** (revision sớm nhất có vật),
không phải chỗ hiện tại: lưới tĩnh không đổi theo các lần dời vật.

Chỉ khoét vật dựng lại từ video và đang được đánh dấu là vật động; vật người dùng thêm từ thư viện không nằm trong lưới.
"""

import numpy as np

from src.models.contracts.coordinates import Transform
from src.models.contracts.scene import SceneIR, SceneObject, SceneObjectOrigin
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.jobs.display_glb import CarveBox, glb_bounds
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.editor import _edited_from

#: Khoét rộng hơn hộp bao của vật một chút: lưới voxel 5 cm bám sát bề mặt vật.
CARVE_MARGIN_M = 0.06
_MAX_REVISIONS = 1000


def _history(registry: ProjectRegistry, job_id: str) -> list[SceneIR]:
    """Các revision từ hiện tại lùi về revision đầu tiên (theo `edited_from`)."""
    scene: SceneIR | None = registry.scene.current(job_id).scene
    chain: list[SceneIR] = []
    while scene is not None and len(chain) < _MAX_REVISIONS:
        chain.append(scene)
        previous = _edited_from(scene)
        revision = registry.scene.revision(job_id, previous) if previous else None
        scene = revision.scene if revision is not None else None
    return chain


def _original_transform(chain: list[SceneIR], object_id: str) -> Transform | None:
    """Transform của vật ở revision sớm nhất còn liền mạch chứa nó."""
    found = None
    for scene in chain:
        item = next((candidate for candidate in scene.objects if candidate.id == object_id), None)
        if item is None:
            break
        found = item.transform
    return found


def _local_bounds(registry: ProjectRegistry, item: SceneObject) -> tuple[np.ndarray, np.ndarray] | None:
    """Hộp bao của vật trong khung của vật: từ kích thước đã lưu, hoặc từ GLB collider."""
    if item.primitive_dimensions_xyz_m is not None:
        half = np.asarray(item.primitive_dimensions_xyz_m) / 2
        return -half, half
    if item.collider is not None and item.collider.geometry_ref is not None:
        try:
            return glb_bounds(registry.runtime_resolver.require(item.collider.geometry_ref).read_bytes())
        except (ArtifactStoreError, ValueError):
            # Không đọc được hình collider thì không khoét vật này (vật vẫn bị lưới tĩnh chặn như trước).
            return None
    return None


def dynamic_carve_boxes(registry: ProjectRegistry, job_id: str, object_ids: list[str]) -> list[CarveBox]:
    """Hộp (hệ canonical) cần khoét khỏi lưới va chạm cho các vật động được yêu cầu; id lạ hoặc vật tĩnh bị bỏ qua."""
    chain = _history(registry, job_id)
    current = {item.id: item for item in chain[0].objects}
    boxes: list[CarveBox] = []
    for object_id in sorted(set(object_ids)):
        item = current.get(object_id)
        if (
            item is None
            or item.origin != SceneObjectOrigin.RECONSTRUCTED
            or not (item.physics and item.physics.dynamic)
        ):
            continue
        transform = _original_transform(chain, object_id)
        bounds = _local_bounds(registry, item)
        if transform is None or bounds is None:
            continue
        low, high = bounds
        x, y, z, w = transform.rotation_quaternion_xyzw
        rotation = np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ]
        )
        center = rotation @ ((low + high) / 2) + np.asarray(transform.translation_xyz)
        boxes.append(
            CarveBox(
                center=tuple(float(value) for value in center),  # type: ignore[arg-type]
                rotation_xyzw=transform.rotation_quaternion_xyzw,
                half_extents=tuple(float(value) for value in (high - low) / 2 + CARVE_MARGIN_M),  # type: ignore[arg-type]
            )
        )
    return boxes
