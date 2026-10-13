"""Trạng thái đã lưu của scene và bản gốc cố định ở revision đầu tiên.

Scene demo dùng để trình diễn: người xem được chỉnh vật thể, xác nhận/loại, dời vật, tạo gói… như scene thường. Khôi
phục đưa **nội dung scene** (môi trường + danh sách vật) về revision đã đánh dấu bằng một revision mới — lịch sử không
bị xoá, các bước xử lý (COLMAP, 3DGS, hình học, tách vật) không chạy lại. Trạng thái duyệt/phát hành gắn theo revision
nên revision mới bắt đầu lại từ "chưa duyệt", đúng như lúc trình diễn lần đầu.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from src.services.orchestration.auth.models import Actor
from src.services.orchestration.projects.models import DemoBaseline
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.errors import (
    SceneEditRejectedError,
    SceneNotAvailableError,
    SceneRevisionConflictError,
)
from src.services.orchestration.scene.objects import restore_revision

_ROOT_REVISION = "rev-001"


class DemoState(BaseModel):
    """Scene đang ở trạng thái đã lưu, bản gốc hay đã được chỉnh sửa."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    baseline: DemoBaseline | None
    current_revision: str | None
    #: True khi nội dung scene hiện tại trùng mốc gốc (kể cả khi đã khôi phục sang revision mới).
    at_baseline: bool
    #: True khi nội dung scene hiện tại trùng bản gốc ban đầu (rev-001) lúc mới xong job.
    at_root: bool = False


def _baseline(registry: ProjectRegistry, job_id: str) -> DemoBaseline | None:
    project = registry.get_project(registry.get_job(job_id).project_id)
    baseline = project.demo_baseline
    return baseline if baseline is not None and baseline.job_id == job_id else None


def demo_state(registry: ProjectRegistry, job_id: str) -> DemoState:
    """Trạng thái bản demo của job; job chưa có SceneIR thì chưa thể là bản demo."""
    baseline = _baseline(registry, job_id)
    try:
        current_rev = registry.scene.current(job_id)
        current = current_rev.scene
    except SceneNotAvailableError:
        current = None

    at_baseline = False
    if baseline is not None and current is not None:
        target = registry.scene.revision(job_id, baseline.scene_revision)
        at_baseline = target is not None and (
            target.scene.environment == current.environment and target.scene.objects == current.objects
        )
    at_root = False
    if current is not None:
        root = registry.scene.revision(job_id, _ROOT_REVISION)
        at_root = root is not None and (
            root.scene.environment == current.environment and root.scene.objects == current.objects
        )
    return DemoState(
        job_id=job_id,
        baseline=baseline,
        current_revision=current.scene_revision if current is not None else None,
        at_baseline=at_baseline,
        at_root=at_root,
    )


def mark_demo(registry: ProjectRegistry, job_id: str, actor: Actor | None) -> DemoState:
    """Lưu revision hiện tại, thay trạng thái đã lưu trước đó nếu có."""
    revision = registry.scene.current(job_id).scene.scene_revision
    project_id = registry.get_job(job_id).project_id
    baseline = DemoBaseline(job_id=job_id, scene_revision=revision, marked_at=datetime.now(UTC), marked_by=actor)
    registry.set_demo_baseline(project_id, baseline)
    return demo_state(registry, job_id)


def clear_demo(registry: ProjectRegistry, job_id: str) -> DemoState:
    """Bỏ trạng thái đã lưu; scene giữ nguyên nội dung hiện tại."""
    if _baseline(registry, job_id) is not None:
        registry.set_demo_baseline(registry.get_job(job_id).project_id, None)
    return demo_state(registry, job_id)


def reset_demo(registry: ProjectRegistry, job_id: str, expected_revision: str) -> DemoState:
    """Khôi phục scene về bản demo gốc; đang ở đúng mốc thì không tạo revision thừa."""
    state = demo_state(registry, job_id)
    if state.baseline is None:
        raise SceneEditRejectedError("Scene này không phải bản demo")
    if not state.at_baseline:
        restore_revision(registry.scene, job_id, expected_revision, state.baseline.scene_revision)
    return demo_state(registry, job_id)


def restore_root(registry: ProjectRegistry, job_id: str, expected_revision: str) -> DemoState:
    """Khôi phục scene về bản gốc ban đầu (rev-001); đang ở đúng bản gốc thì không tạo revision thừa."""
    state = demo_state(registry, job_id)
    if state.current_revision != expected_revision:
        raise SceneRevisionConflictError("scene đã đổi; tải lại trước khi khôi phục bản gốc")
    if not state.at_root:
        restore_revision(registry.scene, job_id, expected_revision, _ROOT_REVISION)
    return demo_state(registry, job_id)
