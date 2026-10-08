"""Scene revision loading and transform editing (PRODUCT-06).

SceneIR là canonical: Three.js không sở hữu transform. Mọi thay đổi phải thành
một revision mới được publish kèm URI + checksum, và client bind lại checksum đó.
Vì vậy editor không sửa `SceneIR` tại chỗ — nó dựng revision kế tiếp.
"""

import json
import re
from collections.abc import Callable
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
from src.services.orchestration.jobs.database import RuntimeStateConflictError, RuntimeTransaction
from src.services.orchestration.scene.errors import (
    SceneEditRejectedError,
    SceneNotAvailableError,
    SceneObjectNotFoundError,
    SceneRevisionConflictError,
)
from src.services.orchestration.scene.heads import SceneHeadRecord, SceneHeadRepository
from src.services.orchestration.scene.identifiers import scene_artifact_uri
from src.services.orchestration.scene.models import (
    SceneEditCommand,
    SceneEditResult,
    SceneRevision,
    TransformEdit,
    VisualBinding,
)

_REVISION_PATTERN = re.compile(r"^(?P<prefix>.*?)(?P<number>\d+)$")
_SCHEMA_VERSION = "1.0"
#: Ceiling for artifact-only recovery; durable scenes use the committed DB head.
_MAX_RECOVERY_STEPS = 1000
#: Revision gốc của mọi job (fixture và scene dựng từ bundle đều bắt đầu từ đây).
_ROOT_REVISION = "rev-001"
#: Số job tối đa giữ lineage đã chứng minh trong bộ nhớ một process.
_LINEAGE_CACHE_JOBS = 8


class SceneEditor:
    """Serve the current SceneIR revision and persist transform edits as new ones."""

    def __init__(
        self,
        fixture_root: Path,
        resolver: ArtifactResolver,
        head_repository: SceneHeadRepository | None = None,
    ) -> None:
        self.fixture_scene_path = fixture_root / "scene_ir" / "scene.json"
        self.fixture_visual_path = fixture_root / "reconstruction_bundle" / "visual_artifact.json"
        self.resolver = resolver
        self.store = FilesystemArtifactStore(resolver)
        self.head_repository = head_repository
        self._revisions: dict[str, SceneRevision] = {}
        #: job_id → (head revision, revisions already proven to be in its lineage, next revision to prove).
        #: Revisions are immutable, so a walk from one head is reused until that job's head moves.
        self._lineage: dict[str, tuple[str, dict[str, SceneRevision], str | None]] = {}

    # --- reading ----------------------------------------------------------

    def current(self, job_id: str) -> SceneRevision:
        """Return the committed DB head, or recover the standalone artifact-only seam.

        DB-backed jobs never infer the current revision from an uncommitted artifact.
        A known fixture may be published through the same head protocol on first use.
        """
        if self.head_repository is not None:
            head = self.head_repository.get(job_id)
            if head is not None:
                revision = self._load_head_revision(head)
                self._revisions[job_id] = revision
                return revision
            pending = self.head_repository.get_publication(job_id)
            if pending is not None:
                raise SceneNotAvailableError("SceneIR publication is not committed; retry or repair the pending writer")
            repair = self.head_repository.get_repair(job_id)
            if repair is not None:
                raise SceneNotAvailableError(
                    f"Scene head is missing while repair is {repair.status}; resume scripts.studio.scene_head first"
                )
            fixture = self._fixture_scene()
            if fixture.environment.geometry_ref.job_id == job_id:
                if self._scene_revision_uris(job_id):
                    raise SceneNotAvailableError(
                        "SceneIR artifacts have no committed head; run scripts.studio.scene_head --apply before reading"
                    )
                return self.publish_initial(job_id, fixture)
            if self._scene_revision_uris(job_id):
                raise SceneNotAvailableError(
                    "SceneIR artifacts have no committed head; run scripts.studio.scene_head --apply before reading"
                )
            raise SceneNotAvailableError("Job chưa publish SceneIR; reconstruction preview không yêu cầu SceneIR")

        if job_id not in self._revisions:
            recovered = self._recover(job_id)
            if recovered is None:
                fixture = self._fixture_scene()
                if fixture.environment.geometry_ref.job_id != job_id:
                    raise SceneNotAvailableError(
                        "Job chưa publish SceneIR; reconstruction preview không yêu cầu SceneIR"
                    )
                if self.head_repository is not None:
                    recovered = self.publish_initial(job_id, fixture)
                else:
                    recovered = self._publish(job_id, fixture, supersedes=None)
            self._revisions[job_id] = recovered
        # Artifact-only seams lack a DB head, so notice a revision published by another process.
        for _ in range(_MAX_RECOVERY_STEPS):
            cached = self._revisions[job_id]
            newer = self._load_revision(job_id, _next_scene_revision(cached.scene.scene_revision), fresh=True)
            if newer is None:
                break
            self._revisions[job_id] = newer
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
        if self.head_repository is not None:
            head = self.head_repository.get(job_id)
            if head is not None:
                return list(self.artifact_references(self._load_head_revision(head).scene))
            if self.head_repository.get_publication(job_id) is not None:
                return []
            if self.head_repository.get_repair(job_id) is not None:
                return []
            fixture = self._fixture_scene()
            return list(self.artifact_references(fixture)) if fixture.environment.geometry_ref.job_id == job_id else []
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
        if scene.environment.visual_master_ref is not None:
            references.append(scene.environment.visual_master_ref)
        if scene.environment.membership is not None:
            for reference in (
                scene.environment.membership.source_visual_ref,
                scene.environment.membership.source_geometry_ref,
                scene.environment.membership.labels_ref,
            ):
                if reference not in references:
                    references.append(reference)
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
        if self.head_repository is not None:
            self._require_committed_head(job_id, scene.scene_revision)
            revision = self._publish_reserved(
                job_id,
                scene.scene_revision,
                updated,
                "transform_edit",
                supersedes=scene.scene_revision,
                record_operation=False,
            )
        else:
            revision = self._publish(job_id, updated, supersedes=scene.scene_revision)
        self._revisions[job_id] = revision
        return SceneEditResult(
            job_id=job_id,
            previous_scene_revision=scene.scene_revision,
            revision=revision,
        )

    def publish_initial(self, job_id: str, scene: SceneIR) -> SceneRevision:
        """Revision đầu của job dựng từ bundle (EX-SCENE). Đã có revision thì giữ nguyên, không ghi đè."""
        if self.head_repository is not None:
            head = self.head_repository.get(job_id)
            if head is not None:
                existing = self._load_head_revision(head)
                self._revisions[job_id] = existing
                return existing
            pending = self.head_repository.get_publication(job_id)
            if pending is None:
                existing_uris = self._scene_revision_uris(job_id)
                if existing_uris:
                    raise SceneEditRejectedError(
                        "SceneIR exists without a verified head; run scripts.studio.scene_head --apply before publishing"
                    )
            if scene.scene_revision != _ROOT_REVISION:
                raise SceneEditRejectedError("revision đầu của job phải là revision gốc (rev-001)")
            revision = self._publish_reserved(
                job_id,
                None,
                with_canonical_checksum(scene, "scene_ir_checksum"),
                "publish_initial",
                supersedes=None,
                record_operation=False,
            )
            self._revisions[job_id] = revision
            return revision
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
        candidate = self._load_revision(job_id, scene_revision)
        if candidate is None or self.head_repository is None:
            return candidate
        head = self.head_repository.get(job_id)
        if head is None:
            return None
        known_head, known, cursor = self._lineage.get(job_id, (head.scene_revision, {}, head.scene_revision))
        if known_head != head.scene_revision:
            known, cursor = {}, head.scene_revision
        else:
            known = dict(known)
        # Walk the committed lineage lazily and remember it: callers such as ownership recovery ask for
        # every ancestor in turn, which would otherwise re-walk from the head each time (O(n²) loads).
        while scene_revision not in known and cursor is not None and cursor not in known:
            current = self._load_revision(job_id, cursor, fresh=True)
            if current is None:
                cursor = None
                break
            known[cursor] = current
            cursor = current.supersedes_revision
        self._lineage.pop(job_id, None)
        self._lineage[job_id] = (head.scene_revision, known, cursor)
        while len(self._lineage) > _LINEAGE_CACHE_JOBS:
            self._lineage.pop(next(iter(self._lineage)))
        return candidate if scene_revision in known else None

    def publish_next(
        self,
        job_id: str,
        expected_revision: str,
        scene: SceneIR,
        operation: str,
        *,
        commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    ) -> SceneEditResult:
        """Publish an EX-SCENE operation at the next reserved immutable revision.

        Optimistic concurrency rejects a stale client before it can publish an artifact.
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
        if self.head_repository is not None:
            self._require_committed_head(job_id, current.scene_revision)
            revision = self._publish_reserved(
                job_id,
                current.scene_revision,
                draft,
                operation,
                supersedes=current.scene_revision,
                record_operation=True,
                commit_guard=commit_guard,
            )
        else:
            if commit_guard is not None:
                raise SceneEditRejectedError("Fenced scene operations require a database-backed scene head")
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

    def _load_revision(self, job_id: str, revision: str, *, fresh: bool = False) -> SceneRevision | None:
        """Đọc một revision đã publish; None nếu chưa có. Hỏng thì raise, không đoán."""
        path = self.resolver.locate(scene_artifact_uri(job_id, revision), fresh=fresh)
        if path is None:
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

    def _load_head_revision(self, head: SceneHeadRecord) -> SceneRevision:
        """Resolve only the exact immutable artifact named by the committed DB head."""
        revision = self._load_revision(head.job_id, head.scene_revision, fresh=True)
        if revision is None:
            raise SceneEditRejectedError("Committed scene head points to a missing SceneIR artifact")
        if (
            revision.scene.scene_id != head.scene_id
            or revision.scene.scene_ir_checksum != head.scene_ir_checksum
            or revision.scene_reference != head.scene_reference
        ):
            raise SceneEditRejectedError("Committed scene head does not match its verified SceneIR artifact")
        return revision

    def _scene_revision_uris(self, job_id: str) -> list[str]:
        """List only SceneIR history; object geometry under the scene prefix is unrelated."""
        prefix = f"artifact://jobs/{job_id}/scene/"
        return [uri for uri in self.resolver.list_uris(prefix) if uri.rsplit("/", 1)[-1].startswith("scene_ir.")]

    def _require_committed_head(self, job_id: str, expected_revision: str) -> SceneHeadRecord:
        """Reject writes against legacy artifact-only state until explicit backfill."""
        assert self.head_repository is not None
        head = self.head_repository.get(job_id)
        if head is None:
            raise SceneEditRejectedError(
                "SceneIR has no committed head; run scripts.studio.scene_head --job-id <job> --apply before editing"
            )
        if head.scene_revision != expected_revision:
            raise SceneRevisionConflictError(
                f"scene đã đổi: client đang giữ {expected_revision}, revision hiện tại là {head.scene_revision}"
            )
        return head

    def _publish_reserved(
        self,
        job_id: str,
        expected_revision: str | None,
        proposed_scene: SceneIR,
        operation: str,
        *,
        supersedes: str | None,
        record_operation: bool,
        commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    ) -> SceneRevision:
        """Reserve, publish, verify, and atomically commit one immutable revision."""
        assert self.head_repository is not None
        pending = None
        try:
            pending = self.head_repository.reserve_publication(job_id, expected_revision, operation)
            if expected_revision is None:
                if pending.target_scene_revision != _ROOT_REVISION:
                    raise SceneEditRejectedError(
                        "An uncommitted initial SceneIR already owns rev-001; run scene-head repair before retrying"
                    )
                updates = {"scene_revision": pending.target_scene_revision}
            else:
                provenance = dict(proposed_scene.provenance)
                provenance["edited_from"] = supersedes
                if record_operation:
                    provenance["operation"] = operation
                updates = {"scene_revision": pending.target_scene_revision, "provenance": provenance}
            scene = with_canonical_checksum(proposed_scene.model_copy(update=updates), "scene_ir_checksum")
            payload = scene.model_dump_json(indent=2).encode("utf-8") + b"\n"
            reference = self._reference_for(job_id, scene.scene_revision, sha256_bytes(payload))
            pending = self.head_repository.bind_publication(pending, reference)
            try:
                self._publish_once(reference, payload)
            except ArtifactAlreadyExistsError as error:
                raise SceneEditRejectedError(
                    "Reserved SceneIR URI already contains different bytes; inspect the orphan before retrying"
                ) from error

            artifact_path = self.resolver.require(reference)
            if artifact_path.read_bytes() != payload:
                raise SceneEditRejectedError("Published SceneIR bytes differ from the reserved payload")
            revision = self._load_revision(job_id, scene.scene_revision, fresh=True)
            if revision is None or revision.scene_reference != reference:
                raise SceneEditRejectedError("Published SceneIR failed exact-reference verification")
            published = self.head_repository.mark_published(pending)
            if commit_guard is None:
                self.head_repository.commit_publication(published, revision)
            else:
                self.head_repository.commit_publication(published, revision, commit_guard=commit_guard)
            self._revisions[job_id] = revision
            return revision
        except BaseException as error:
            if pending is not None:
                try:
                    self.head_repository.abort_publication(pending)
                except Exception as cleanup_error:
                    error.add_note(f"Could not mark failed scene publication aborted: {cleanup_error}")
            if isinstance(error, RuntimeStateConflictError):
                raise SceneRevisionConflictError(str(error)) from error
            raise

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
            existing = self.resolver.locate(reference.artifact_uri)
            if existing is None or existing.read_bytes() != payload:
                raise


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
