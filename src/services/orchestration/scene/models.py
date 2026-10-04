"""Commands and revision views for the scene edit flow (PRODUCT-06)."""

from typing import Self

from pydantic import model_validator

from src.models.contracts.artifacts import ArtifactRef, Checksum, ContractModel, Identifier
from src.models.contracts.scene import SceneIR


class TransformEdit(ContractModel):
    """Một thay đổi transform cho một SceneObject.

    Chỉ nhận phần được phép sửa; `parent_frame`/`local_frame` do SceneIR quyết
    định, client không được đổi để tránh phá quan hệ cha–con canonical.
    """

    object_id: Identifier
    translation_xyz: tuple[float, float, float] | None = None
    rotation_quaternion_xyzw: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def _require_a_change(self) -> Self:
        if self.translation_xyz is None and self.rotation_quaternion_xyzw is None:
            raise ValueError("transform edit phải đổi ít nhất translation hoặc rotation")
        return self


class SceneEditCommand(ContractModel):
    """Yêu cầu sửa scene, khoá theo revision mà client đang thấy."""

    expected_scene_revision: Identifier
    edits: list[TransformEdit]

    @model_validator(mode="after")
    def _require_edits(self) -> Self:
        if not self.edits:
            raise ValueError("scene edit phải có ít nhất một thay đổi")
        targets = [edit.object_id for edit in self.edits]
        if len(set(targets)) != len(targets):
            raise ValueError("mỗi object chỉ được xuất hiện một lần trong một command")
        return self


class SceneObjectVisibility(ContractModel):
    """Lớp hiển thị của một scene object; không phải canonical state.

    `active` là dữ liệu canonical trong SceneIR. `visible` chỉ là lựa chọn xem
    của client nên **không** được persist thành scene revision.
    """

    object_id: Identifier
    visible: bool


class SceneRevision(ContractModel):
    """Một revision SceneIR đã publish, kèm ref để client bind checksum."""

    job_id: Identifier
    scene: SceneIR
    scene_reference: ArtifactRef
    supersedes_revision: Identifier | None = None


class SceneEditResult(ContractModel):
    """Kết quả một lần sửa: revision mới và ref của nó."""

    job_id: Identifier
    previous_scene_revision: Identifier
    revision: SceneRevision


class VisualBinding(ContractModel):
    """Trạng thái visual của scene, kèm cờ nói rõ đây có phải bằng chứng Brush.

    Sai lầm nguy hiểm nhất ở đây là để một visual tổng hợp bị đọc thành
    "đã render được 3DGS thật". Vì vậy cờ này đi kèm payload chứ không nằm
    trong tài liệu.
    """

    available: bool
    format: Identifier | None = None
    producer: Identifier | None = None
    producer_version: str | None = None
    reference: ArtifactRef | None = None
    source_input_checksum: Checksum | None = None
    brush_compatibility_proof: bool = False
    unavailable_reason: str | None = None
