"""Scene revision loading and transform editing (PRODUCT-06).

SceneIR là canonical: Three.js không sở hữu transform. Mọi thay đổi phải thành
một revision mới được publish kèm URI + checksum, và client bind lại checksum đó.
Vì vậy editor không sửa `SceneIR` tại chỗ — nó dựng revision kế tiếp.
"""

import json
import re
from pathlib import Path

from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.scene import SceneIR, SceneObject
from src.services.orchestration.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactResolver,
    FilesystemArtifactStore,
    sha256_bytes,
    with_canonical_checksum,
)
from src.services.orchestration.scene.errors import (
    SceneEditRejectedError,
    SceneObjectNotFoundError,
    SceneRevisionConflictError,
)
from src.services.orchestration.scene.models import (
    SceneEditCommand,
    SceneEditResult,
    SceneRevision,
    TransformEdit,
    VisualBinding,
)

_REVISION_PATTERN = re.compile(r"^(?P<prefix>.*?)(?P<number>\d+)$")
_SCHEMA_VERSION = "1.0"


class SceneEditor:
    """Serve the current SceneIR revision and persist transform edits as new ones."""

    def __init__(self, fixture_root: Path, resolver: ArtifactResolver) -> None:
        self.fixture_scene_path = fixture_root / "scene_ir" / "scene.json"
        self.fixture_visual_path = fixture_root / "reconstruction_bundle" / "visual_artifact.json"
        self.resolver = resolver
        self.store = FilesystemArtifactStore(resolver)
        self._revisions: dict[str, SceneRevision] = {}

    # --- reading ----------------------------------------------------------

    def current(self, job_id: str) -> SceneRevision:
        """Revision hiện tại của một job, seed từ fixture ở lần đọc đầu tiên."""
        if job_id not in self._revisions:
            self._revisions[job_id] = self._publish(job_id, self._fixture_scene(), supersedes=None)
        return self._revisions[job_id]

    def visual_binding(self) -> VisualBinding:
        """Visual của scene, kèm cờ nói rõ đây chưa phải bằng chứng Brush.

        Fixture hiện chỉ có visual tổng hợp (`real2sim.synthetic.visual.v1` với
        `brush_compatibility_proof: false`). Trả `available: true` để viewer vẫn
        dựng được, nhưng cờ false ngăn nó bị đọc thành AC-11.
        """
        if not self.fixture_visual_path.is_file():
            return VisualBinding(available=False, unavailable_reason="chưa có VisualArtifact nào được publish")
        payload = json.loads(self.fixture_visual_path.read_text(encoding="utf-8"))
        provenance = payload.get("provenance", {})
        return VisualBinding(
            available=True,
            format=payload["format"],
            producer=payload["producer"],
            producer_version=payload["producer_version"],
            reference=ArtifactRef(
                artifact_type=payload["artifact_type"],
                schema_version=payload["schema_version"],
                artifact_uri=payload["artifact_uri"],
                artifact_checksum=payload["artifact_checksum"],
                data_class=ArtifactDataClass.DERIVED,
                producer_stage=payload["producer_stage"],
                job_id=payload["job_id"],
                source_provenance=provenance,
            ),
            source_input_checksum=payload["source_input_checksum"],
            brush_compatibility_proof=bool(provenance.get("brush_compatibility_proof", False)),
        )

    # --- writing ----------------------------------------------------------

    @staticmethod
    def artifact_references(scene: SceneIR) -> list[ProductArtifactRef]:
        """Mọi ref hình học mà viewer cần tải cho revision này.

        Trả đúng kiểu `ProductArtifactRef`, nên `ground_truth`/`evaluation_only`
        không thể xuất hiện ở đây — contract đã chặn từ lúc dựng SceneIR.
        """
        references = [scene.environment.geometry_ref]
        if scene.environment.collider_ref is not None:
            references.append(scene.environment.collider_ref)
        for item in scene.objects:
            references.append(item.geometry_ref)
            if item.collider is not None and item.collider.geometry_ref is not None:
                references.append(item.collider.geometry_ref)
        return references

    def apply(self, job_id: str, command: SceneEditCommand) -> SceneEditResult:
        """Áp một command lên revision hiện tại và publish revision kế tiếp."""
        previous = self.current(job_id)
        scene = previous.scene
        if command.expected_scene_revision != scene.scene_revision:
            raise SceneRevisionConflictError(
                f"scene đã đổi: client đang giữ {command.expected_scene_revision}, "
                f"revision hiện tại là {scene.scene_revision}"
            )
        self.require_known_objects(scene, command)
        updated = self._build_revision(scene, command)
        revision = self._publish(job_id, updated, supersedes=scene.scene_revision)
        self._revisions[job_id] = revision
        return SceneEditResult(
            job_id=job_id,
            previous_scene_revision=scene.scene_revision,
            revision=revision,
        )

    @classmethod
    def _build_revision(cls, scene: SceneIR, command: SceneEditCommand) -> SceneIR:
        """Dựng SceneIR kế tiếp; revision cũ không bao giờ bị sửa.

        Object không có edit phải được giữ nguyên — bỏ sót chúng là mất dữ liệu
        scene, không chỉ là thiếu một thay đổi.
        """
        objects = []
        for item in scene.objects:
            edits = cls._edits_for(item, command)
            objects.append(cls._apply_edit(item, edits[0]) if edits else item)
        draft = scene.model_copy(
            update={
                "scene_revision": _next_scene_revision(scene.scene_revision),
                "objects": objects,
                "provenance": {
                    **scene.provenance,
                    "edited_from": scene.scene_revision,
                    "edited_objects": [edit.object_id for edit in command.edits],
                },
            }
        )
        return with_canonical_checksum(draft, "scene_ir_checksum")

    @staticmethod
    def _edits_for(item: SceneObject, command: SceneEditCommand) -> list[TransformEdit]:
        """Các edit nhắm vào object này; rỗng nghĩa là object giữ nguyên."""
        return [edit for edit in command.edits if edit.object_id == item.id]

    @staticmethod
    def _apply_edit(item: SceneObject, edit: TransformEdit) -> SceneObject:
        """Dựng Transform mới qua constructor để validator quaternion chạy lại.

        `model_copy(update=...)` bỏ qua validation, nên một quaternion không
        chuẩn hoá sẽ lọt vào canonical revision nếu đi đường đó.
        """
        current = item.transform
        try:
            updated = Transform(
                parent_frame=current.parent_frame,
                local_frame=current.local_frame,
                translation_xyz=edit.translation_xyz or current.translation_xyz,
                rotation_quaternion_xyzw=edit.rotation_quaternion_xyzw or current.rotation_quaternion_xyzw,
            )
        except ValidationError as error:
            raise SceneEditRejectedError(f"transform không hợp lệ cho {item.id}: {error}") from error
        return item.model_copy(update={"transform": updated})

    def require_known_objects(self, scene: SceneIR, command: SceneEditCommand) -> None:
        """Từ chối cả command nếu có object id không tồn tại trong revision."""
        known = {item.id for item in scene.objects}
        for edit in command.edits:
            if edit.object_id not in known:
                raise SceneObjectNotFoundError(f"không tìm thấy scene object: {edit.object_id}")

    # --- publication ------------------------------------------------------

    def _fixture_scene(self) -> SceneIR:
        """Nạp SceneIR mẫu và xác nhận self-checksum canonical của nó đúng."""
        scene = SceneIR.model_validate_json(self.fixture_scene_path.read_text(encoding="utf-8"))
        if scene.scene_ir_checksum != with_canonical_checksum(scene, "scene_ir_checksum").scene_ir_checksum:
            raise SceneEditRejectedError("SceneIR mẫu có checksum không khớp canonical content")
        return scene

    def _publish(self, job_id: str, scene: SceneIR, supersedes: str | None) -> SceneRevision:
        """Ghi revision thành artifact bất biến và trả ref đã verify.

        Hai checksum khác vai: `scene_ir_checksum` trong document là canonical
        content checksum của SceneIR, còn `artifact_checksum` của ref là **byte**
        hash của file đã publish. Client bind byte hash để kiểm tra đúng bytes nó
        tải về, không phải để suy ra nội dung canonical.
        """
        payload = scene.model_dump_json(indent=2).encode("utf-8") + b"\n"
        reference = ArtifactRef(
            artifact_type="SceneIR",
            schema_version=_SCHEMA_VERSION,
            artifact_uri=scene_artifact_uri(job_id, scene.scene_revision),
            artifact_checksum=sha256_bytes(payload),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.EDIT,
            job_id=job_id,
        )
        self._publish_once(reference, payload)
        return SceneRevision(
            job_id=job_id,
            scene=scene,
            scene_reference=reference,
            supersedes_revision=supersedes,
        )

    def _publish_once(self, reference: ArtifactRef, payload: bytes) -> None:
        """Publish idempotent: cùng revision nghĩa là cùng bytes nên ghi lại là no-op.

        Artifact đã tồn tại mà nội dung khác thì đó là bất biến bị vi phạm, và
        `ArtifactAlreadyExistsError` phải nổi lên chứ không được nuốt.
        """
        try:
            self.store.publish(reference, payload)
        except ArtifactAlreadyExistsError:
            if self.resolver.resolve(reference.artifact_uri).read_bytes() != payload:
                raise


def scene_artifact_uri(job_id: str, scene_revision: str) -> str:
    """URI logic cho một revision SceneIR; đường dẫn đĩa không bao giờ lộ ra API."""
    return f"artifact://jobs/{job_id}/scene/scene_ir.{scene_revision}.json"


def _next_scene_revision(current: str) -> str:
    """Tăng phần số của revision, giữ nguyên tiền tố (`rev-001` → `rev-002`)."""
    match = _REVISION_PATTERN.match(current)
    if match is None:
        raise SceneEditRejectedError(f"không suy ra được revision kế tiếp từ: {current}")
    number = int(match.group("number"))
    return f"{match.group('prefix')}{number + 1:0{len(match.group('number'))}d}"
