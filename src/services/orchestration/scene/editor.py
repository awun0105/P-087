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
    sha256_file,
    with_canonical_checksum,
)
from src.services.orchestration.scene.errors import (
    SceneEditRejectedError,
    SceneNotAvailableError,
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
#: Chặn trên cho vòng dò revision lúc phục hồi; revision tăng 1 mỗi lần sửa.
_MAX_RECOVERY_STEPS = 1000
#: Revision gốc của mọi job (fixture và scene dựng từ bundle đều bắt đầu từ đây).
_ROOT_REVISION = "rev-001"


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
        """Revision hiện tại của một job.

        Đọc lần đầu thì phục hồi revision cao nhất đã publish trên đĩa; job chưa có
        gì mới seed từ fixture. Không có bước này thì revision chỉ sống trong bộ nhớ
        tiến trình, và sau khi restart editor sẽ phục vụ revision cũ rồi đụng
        `ArtifactAlreadyExistsError` ở lần sửa kế tiếp.
        """
        if job_id not in self._revisions:
            recovered = self._recover(job_id)
            if recovered is None:
                fixture = self._fixture_scene()
                if fixture.environment.geometry_ref.job_id != job_id:
                    raise SceneNotAvailableError(
                        "Job chưa publish SceneIR; reconstruction preview không yêu cầu SceneIR"
                    )
                recovered = self._publish(job_id, fixture, supersedes=None)
            self._revisions[job_id] = recovered
        return self._revisions[job_id]

    def visual_binding(self, job_id: str | None = None) -> VisualBinding:
        """Visual của scene, kèm cờ nói rõ đây chưa phải bằng chứng Brush.

        Fixture hiện chỉ có visual tổng hợp (`real2sim.synthetic.visual.v1` với
        `brush_compatibility_proof: false`). JSON fixture vẫn có ref để inspect,
        nhưng không được khai available cho Gaussian renderer.
        """
        if not self.fixture_visual_path.is_file():
            return VisualBinding(available=False, unavailable_reason="chưa có VisualArtifact nào được publish")
        payload = json.loads(self.fixture_visual_path.read_text(encoding="utf-8"))
        if job_id is not None and payload["job_id"] != job_id:
            return VisualBinding(available=False, unavailable_reason="Job chưa có visual binding đã publish")
        provenance = payload.get("provenance", {})
        supported = payload["artifact_uri"].lower().endswith((".sog", ".ply"))
        return VisualBinding(
            available=supported,
            unavailable_reason=None if supported else "Fixture visual JSON không phải Gaussian PLY/SOG có thể render",
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

    def artifact_references_for_job(self, job_id: str) -> list[ArtifactRef]:
        """Đọc allow-list không tạo revision; fixture chỉ thuộc đúng fixture job."""
        revision = self._revisions.get(job_id) or self._recover(job_id)
        if revision is not None:
            return list(self.artifact_references(revision.scene))
        fixture = self._fixture_scene()
        if fixture.environment.geometry_ref.job_id != job_id:
            return []
        return list(self.artifact_references(fixture))

    @staticmethod
    def artifact_references(scene: SceneIR) -> list[ProductArtifactRef]:
        """Mọi ref hình học mà viewer cần tải cho revision này.

        Trả đúng kiểu `ProductArtifactRef`, nên `ground_truth`/`evaluation_only`
        không thể xuất hiện ở đây — contract đã chặn từ lúc dựng SceneIR.
        """
        references = [scene.environment.geometry_ref]
        if scene.environment.collider_ref is not None:
            references.append(scene.environment.collider_ref)
        if scene.environment.visual_ref is not None:
            references.append(scene.environment.visual_ref)
        for item in scene.objects:
            references.append(item.geometry_ref)
            # Scene theo vật (pipeline v2): Gaussian riêng của từng vật cho viewer.
            if item.visual_ref is not None:
                references.append(item.visual_ref)
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

    def publish_initial(self, job_id: str, scene: SceneIR) -> SceneRevision:
        """Revision đầu của job dựng từ bundle (EX-SCENE). Đã có revision thì giữ nguyên, không ghi đè."""
        existing = self._recover(job_id)
        if existing is not None:
            self._revisions[job_id] = existing
            return existing
        if scene.scene_revision != _ROOT_REVISION:
            raise SceneEditRejectedError("revision đầu của job phải là revision gốc (rev-001)")
        revision = self._publish(job_id, with_canonical_checksum(scene, "scene_ir_checksum"), supersedes=None)
        self._revisions[job_id] = revision
        return revision

    def revision(self, job_id: str, scene_revision: str) -> SceneRevision | None:
        """Một revision đã publish của job (đọc lại, kiểm checksum); None nếu chưa có."""
        return self._load_revision(job_id, scene_revision)

    def publish_next(self, job_id: str, expected_revision: str, scene: SceneIR, operation: str) -> SceneEditResult:
        """Publish kết quả một thao tác domain EX-SCENE (xác nhận/loại/thêm vật) thành revision kế tiếp.

        Khoá optimistic như `apply`: client giữ revision cũ thì 409, không ghi đè.
        """
        previous = self.current(job_id)
        current = previous.scene
        if expected_revision != current.scene_revision:
            raise SceneRevisionConflictError(
                f"scene đã đổi: client đang giữ {expected_revision}, revision hiện tại là {current.scene_revision}"
            )
        draft = scene.model_copy(
            update={
                "scene_revision": _next_scene_revision(current.scene_revision),
                "provenance": {**scene.provenance, "edited_from": current.scene_revision, "operation": operation},
            }
        )
        revision = self._publish(
            job_id, with_canonical_checksum(draft, "scene_ir_checksum"), supersedes=current.scene_revision
        )
        self._revisions[job_id] = revision
        return SceneEditResult(job_id=job_id, previous_scene_revision=current.scene_revision, revision=revision)

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

    # --- recovery ---------------------------------------------------------

    def _recover(self, job_id: str) -> SceneRevision | None:
        """Revision cao nhất đã publish trên đĩa; None nếu job chưa có gì.

        `ArtifactResolver` cố ý không có API liệt kê thư mục, nên dò tăng dần từ
        revision gốc. Chuỗi revision liền mạch theo cấu trúc vì
        `_next_scene_revision` luôn cộng một, nên dừng ở revision đầu tiên chưa có
        là đúng; job mới chỉ tốn một lần kiểm tra tồn tại.
        """
        revision = _ROOT_REVISION
        latest: SceneRevision | None = None
        for _ in range(_MAX_RECOVERY_STEPS):
            recovered = self._load_revision(job_id, revision)
            if recovered is None:
                return latest
            latest = recovered
            revision = _next_scene_revision(revision)
        raise SceneEditRejectedError(f"chuỗi revision của {job_id} vượt {_MAX_RECOVERY_STEPS} bước")

    def _load_revision(self, job_id: str, revision: str) -> SceneRevision | None:
        """Đọc một revision đã publish; None nếu chưa có. Hỏng thì raise, không đoán."""
        path = self.resolver.resolve(scene_artifact_uri(job_id, revision))
        if not path.is_file():
            return None
        reference = self._reference_for(job_id, revision, sha256_file(path))
        scene = SceneIR.model_validate_json(path.read_text(encoding="utf-8"))
        self._require_consistent(scene, revision)
        return SceneRevision(
            job_id=job_id,
            scene=scene,
            scene_reference=reference,
            supersedes_revision=_edited_from(scene),
        )

    @staticmethod
    def _require_consistent(scene: SceneIR, revision: str) -> None:
        """Artifact đã publish phải tự khớp: đúng tên revision, đúng canonical checksum.

        Checksum ở đây không so với ref (ref được suy ra từ chính file nên phép so
        đó rỗng nghĩa); nó kiểm nội dung document có khớp `scene_ir_checksum` mà
        document tự khai hay không. Lệch nghĩa là artifact đã bị sửa tay hoặc ghi
        hỏng, và phục vụ nó sẽ lan cái sai vào revision kế tiếp.
        """
        if scene.scene_revision != revision:
            raise SceneEditRejectedError(f"artifact {revision} chứa scene_revision {scene.scene_revision}")
        if scene.scene_ir_checksum != with_canonical_checksum(scene, "scene_ir_checksum").scene_ir_checksum:
            raise SceneEditRejectedError(f"SceneIR {revision} có checksum không khớp canonical content")

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
        reference = self._reference_for(job_id, scene.scene_revision, sha256_bytes(payload))
        self._publish_once(reference, payload)
        return SceneRevision(
            job_id=job_id,
            scene=scene,
            scene_reference=reference,
            supersedes_revision=supersedes,
        )

    @staticmethod
    def _reference_for(job_id: str, scene_revision: str, checksum: str) -> ArtifactRef:
        """Ref của một revision đã publish.

        Đường ghi mới và đường phục hồi phải dựng ra ref **bằng nhau từng field**,
        nếu không thì cùng một revision lại có hai ref khác nhau tuỳ theo tiến trình
        nào đọc nó — client bind checksum sẽ so sai.
        """
        return ArtifactRef(
            artifact_type="SceneIR",
            schema_version=_SCHEMA_VERSION,
            artifact_uri=scene_artifact_uri(job_id, scene_revision),
            artifact_checksum=checksum,
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.EDIT,
            job_id=job_id,
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


def _edited_from(scene: SceneIR) -> str | None:
    """Revision trước đó, lấy từ provenance do `_build_revision` ghi.

    `supersedes_revision` không nằm trong artifact đã publish, nhưng `edited_from`
    thì có — nên phục hồi đọc lại được chuỗi revision thay vì trả `None` giả.
    """
    previous = scene.provenance.get("edited_from")
    return previous if isinstance(previous, str) else None
