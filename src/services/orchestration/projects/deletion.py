"""Thùng rác scene: gỡ scene khỏi Studio theo cách khôi phục được, và xoá hẳn khi người dùng chọn.

Dùng chung cho trang Thùng rác của Studio (STUDIO_UX_SPEC D-15, API `studio/trash.py`) và CLI vận hành `delete_cli`.

Một scene = project + các job của nó. Gỡ scene kéo theo journal và yêu cầu dựng lại vật của job, thư mục artifact của
job/project, thư mục làm việc của worker và bản ghi Rerun. Upload nguồn chỉ bị gỡ khi không còn scene hay bản nhập nào
dùng nó. Scene nhập (import) được gỡ theo cùng cách.

Thứ tự: trong một transaction, ghi bản ghi vào bảng `r2s_trash` (đủ để khôi phục) và xoá các dòng DB của scene → rồi
chuyển thư mục vào thùng rác. Dừng giữa chừng chỉ để lại thư mục chưa dời, DB không bao giờ trỏ tới file đã mất.
`restore_deletion` làm ngược lại; chỉ `purge_deletion` mới xoá hẳn. Bản ghi nằm trong DB vì đĩa của API trên cloud
không bền.

Deployment có kho file S3/R2: lúc gỡ, object trên kho được giữ nguyên (không còn dòng DB nào trỏ tới, và `restore`
không phải tải lại); `purge_deletion` xoá mọi object của các namespace đã gỡ rồi mới xoá thư mục thùng rác.

Từ chối (fail closed): job đang chờ worker hoặc đang chạy, bản nhập đang đóng gói, yêu cầu dựng lại vật đang chờ/chạy,
scene đã có bản phát hành (PRD US-06) khi chưa cho phép rõ ràng.
"""

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.config import Settings
from src.models.contracts.artifacts import ArtifactRef, Identifier
from src.models.contracts.manifests import JobManifest, JobStatus, StageId
from src.services.orchestration.artifacts import ArtifactResolver, ArtifactStoreError
from src.services.orchestration.auth.models import AuditEntry
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError, RuntimeTransaction
from src.services.orchestration.jobs.progress import metric_confirmation_stage
from src.services.orchestration.storage import runtime_resolver
from src.services.orchestration.uploads.models import UploadRecord

RECORD_NAME = "deletion_record.json"
ItemKind = Literal["artifact", "worker", "import_worker", "rerun"]

_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
#: Cột của từng bảng, liệt kê theo thứ tự chèn lại khi khôi phục (cha trước con); khoá chính đứng đầu.
#: SQL trong module này chỉ ghép từ các hằng số ở đây, giá trị luôn đi qua bind parameter.
_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "r2s_projects": ("project_id", "payload"),
    "r2s_jobs": ("job_id", "project_id", "version", "manifest_ref"),
    "r2s_job_events": ("job_id", "version", "payload"),
    "r2s_scene_requests": ("job_id", "status", "payload"),
    "r2s_uploads": ("upload_id", "payload"),
    "r2s_upload_sessions": ("upload_id", "payload"),
    "r2s_imports": ("import_id", "upload_id", "payload"),
}
_KEY_WIDTH = {"r2s_job_events": 2}
#: Con trước cha, theo khoá ngoại của schema runtime.
_DELETE_ORDER = (
    "r2s_scene_requests",
    "r2s_job_events",
    "r2s_jobs",
    "r2s_projects",
    "r2s_imports",
    "r2s_upload_sessions",
    "r2s_uploads",
)


class DeletionRefusedError(ValueError):
    """Yêu cầu gỡ/khôi phục bị từ chối; `reasons` là từng lý do hiển thị được cho người vận hành."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class DeletionRequest(BaseModel):
    """ID người vận hành muốn gỡ.

    Upload của scene/bản nhập bị gỡ được xét tự động; `upload_ids` chỉ dành cho upload không còn ai dùng.
    """

    model_config = ConfigDict(extra="forbid")

    project_ids: list[Identifier] = Field(default_factory=list)
    import_ids: list[Identifier] = Field(default_factory=list)
    upload_ids: list[Identifier] = Field(default_factory=list)
    allow_released: bool = False


class StoredRow(BaseModel):
    """Một dòng DB bị gỡ, giữ nguyên giá trị để chèn lại khi khôi phục."""

    model_config = ConfigDict(extra="forbid")

    table: str
    values: dict[str, str | int]


class UploadUnlink(BaseModel):
    """Upload được giữ vì scene khác còn dùng; chỉ bỏ các project đã gỡ khỏi danh sách của nó."""

    model_config = ConfigDict(extra="forbid")

    upload_id: str
    removed_project_ids: list[str]
    original_project_ids: list[str]
    original_payload: str


class MovedItem(BaseModel):
    """Một thư mục/file của scene, định vị bằng loại + tên để bản ghi không chứa đường dẫn của máy."""

    model_config = ConfigDict(extra="forbid")

    kind: ItemKind
    name: str


class SummaryLine(BaseModel):
    """Dòng tóm tắt để người vận hành đối chiếu trước khi gỡ."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["scene", "import", "upload"]
    identifier: str
    name: str
    detail: str


class DeletionPlan(BaseModel):
    """Mọi thứ một yêu cầu sẽ gỡ, cùng lý do từ chối nếu có; tính xong mà chưa sửa gì."""

    model_config = ConfigDict(extra="forbid")

    request: DeletionRequest
    summary: list[SummaryLine]
    rows: list[StoredRow]
    upload_unlinks: list[UploadUnlink]
    items: list[MovedItem]
    #: Namespace `jobs/<ns>` của mọi thứ bị gỡ, kể cả khi máy này không có bản cache; purge dùng để xoá trên kho file.
    remote_namespaces: list[str] = Field(default_factory=list)
    size_bytes: int
    blockers: list[str]


class DeletionRecord(BaseModel):
    """Bản ghi của một lần gỡ = một mục trong thùng rác (một dòng `r2s_trash`).

    `state` chỉ còn để đọc bản ghi dạng file của phiên bản trước (`deletion_record.json`); mục trong DB luôn là
    `removed`, khôi phục hoặc xoá hẳn thì dòng bị xoá.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    entry_id: str
    created_at: datetime
    state: Literal["planned", "removed", "restored"] = "removed"
    deleted_by: str | None = None
    plan: DeletionPlan


def _safe(name: str) -> str:
    """ID lấy từ DB vẫn phải là một tên thư mục đơn; không cho ký tự thoát khỏi thư mục gốc."""
    if _SAFE_NAME.fullmatch(name) is None:
        raise DeletionRefusedError([f"ID không hợp lệ để định vị thư mục: {name!r}"])
    return name


@dataclass(frozen=True)
class DeletionContext:
    """Nơi dữ liệu của Studio nằm trên máy này; CLI dựng từ Settings."""

    database: RuntimeDatabase
    resolver: ArtifactResolver
    worker_root: Path
    rerun_dir: Path
    trash_root: Path

    def entry_dir(self, entry_id: str) -> Path:
        """Thư mục giữ file của một mục thùng rác."""
        return self.trash_root / _safe(entry_id)

    def live_path(self, item: MovedItem) -> Path:
        """Vị trí đang dùng của một mục."""
        name = _safe(item.name)
        if item.kind == "artifact":
            return self.resolver.artifact_root / "jobs" / name
        if item.kind == "worker":
            return self.worker_root / name
        if item.kind == "import_worker":
            return self.worker_root / "imports" / name
        return self.rerun_dir / f"{name}.rrd"


def trash_path(entry: Path, item: MovedItem) -> Path:
    """Vị trí của một mục trong thư mục thùng rác của lần gỡ."""
    name = _safe(item.name)
    return entry / item.kind / (f"{name}.rrd" if item.kind == "rerun" else name)


def _tree_size(paths: list[Path]) -> int:
    """Dung lượng thật trên đĩa: file dùng chung inode (hardlink) chỉ tính một lần."""
    seen: set[tuple[int, int]] = set()
    total = 0
    for path in paths:
        files = [path] if path.is_file() else [Path(root) / name for root, _, names in os.walk(path) for name in names]
        for file in files:
            info = file.lstat()
            if (info.st_dev, info.st_ino) not in seen:
                seen.add((info.st_dev, info.st_ino))
                total += info.st_size
    return total


def _busy_reason(job: JobManifest) -> str | None:
    """Job còn có thể được worker đụng tới thì chưa gỡ được; job chờ người dùng xác nhận tỉ lệ thì đã dừng."""
    if job.status == JobStatus.QUEUED:
        return "job đang chờ worker (QUEUED); huỷ job trước khi gỡ"
    if job.status == JobStatus.RUNNING:
        waiting_for_user = job.current_stage == StageId.METRIC_CANONICALIZE and metric_confirmation_stage(job) is None
        if not waiting_for_user:
            return f"worker có thể đang xử lý job (RUNNING ở {job.current_stage.value}); huỷ job trước khi gỡ"
    return None


class _Collector:
    """Gom dòng DB, thư mục và lý do từ chối cho một yêu cầu gỡ; chỉ đọc."""

    def __init__(self, context: DeletionContext, tx: RuntimeTransaction, request: DeletionRequest) -> None:
        self.context = context
        self.tx = tx
        self.request = request
        self.rows: list[StoredRow] = []
        self.items: list[MovedItem] = []
        self.namespaces: list[str] = []
        self.summary: list[SummaryLine] = []
        self.unlinks: list[UploadUnlink] = []
        self.blockers: list[str] = []

    def plan(self) -> DeletionPlan:
        """Xét lần lượt scene, bản nhập rồi upload (upload phụ thuộc hai nhóm trước)."""
        request = self.request
        if not (request.project_ids or request.import_ids or request.upload_ids):
            self.blockers.append("chưa nêu scene, bản nhập hay upload nào để gỡ")
        for project_id in dict.fromkeys(request.project_ids):
            self._add_project(project_id)
        for import_id in dict.fromkeys(request.import_ids):
            self._add_import(import_id)
        self._add_uploads()
        return DeletionPlan(
            request=request,
            summary=self.summary,
            rows=self.rows,
            upload_unlinks=self.unlinks,
            items=self.items,
            remote_namespaces=self.namespaces,
            size_bytes=_tree_size([self.context.live_path(item) for item in self.items]),
            blockers=self.blockers,
        )

    def _select(self, table: str, where: str, parameters: tuple) -> list[StoredRow]:
        columns = _TABLE_COLUMNS[table]
        query = f"SELECT {', '.join(columns)} FROM {table} WHERE {where}" + self.tx.lock_suffix()
        rows = self.tx.execute(query, parameters).fetchall()
        return [StoredRow(table=table, values=dict(zip(columns, row, strict=True))) for row in rows]

    def _add_item(self, kind: ItemKind, name: str) -> None:
        item = MovedItem(kind=kind, name=name)
        if kind == "artifact":
            self.namespaces.append(_safe(name))
        if self.context.live_path(item).exists():
            self.items.append(item)

    def _add_project(self, project_id: str) -> None:
        found = self._select("r2s_projects", "project_id=?", (project_id,))
        if not found:
            self.blockers.append(f"{project_id}: không tìm thấy scene")
            return
        jobs = self._select("r2s_jobs", "project_id=? ORDER BY job_id", (project_id,))
        states = [self._add_job(str(row.values["job_id"]), str(row.values["manifest_ref"])) for row in jobs]
        self.rows += jobs + found
        self._add_item("artifact", project_id)
        name = str(json.loads(str(found[0].values["payload"])).get("name", "?"))
        detail = "; ".join(states) or "chưa có job"
        self.summary.append(SummaryLine(kind="scene", identifier=project_id, name=name, detail=detail))

    def _add_job(self, job_id: str, manifest_ref: str) -> str:
        """Gom dữ liệu của một job; trả mô tả trạng thái và ghi lý do từ chối nếu job chưa gỡ được."""
        requests = self._select("r2s_scene_requests", "job_id=?", (job_id,))
        if any(row.values["status"] in {"queued", "running"} for row in requests):
            self.blockers.append(f"{job_id}: yêu cầu dựng lại vật thể đang chờ hoặc đang chạy")
        self.rows += requests + self._select("r2s_job_events", "job_id=? ORDER BY version", (job_id,))
        for kind in ("artifact", "worker", "rerun"):
            self._add_item(kind, job_id)
        try:
            job = self.context.resolver.load_model(ArtifactRef.model_validate_json(manifest_ref), JobManifest)
        except (ArtifactStoreError, ValueError) as error:
            self.blockers.append(f"{job_id}: không đọc được JobManifest ({type(error).__name__}); kiểm scene trước")
            return f"{job_id} không đọc được trạng thái"
        reason = _busy_reason(job)
        if reason is not None:
            self.blockers.append(f"{job_id}: {reason}")
        release_dir = self.context.resolver.artifact_root / "jobs" / _safe(job_id) / "release"
        if not self.request.allow_released and any(release_dir.glob("*/release_manifest.json")):
            self.blockers.append(f"{job_id}: scene đã có bản phát hành (PRD US-06); gỡ cần --allow-released")
        return f"{job_id} {job.status.value} ở {job.current_stage.value}"

    def _add_import(self, import_id: str) -> None:
        found = self._select("r2s_imports", "import_id=?", (import_id,))
        if not found:
            self.blockers.append(f"{import_id}: không tìm thấy scene nhập")
            return
        payload = json.loads(str(found[0].values["payload"]))
        if payload.get("status") == "PACKAGING":
            self.blockers.append(f"{import_id}: scene nhập đang được đóng gói")
        self.rows += found
        self._add_item("artifact", import_id)
        self._add_item("import_worker", import_id)
        detail = f"{payload.get('status', '?')}, từ {found[0].values['upload_id']}"
        self.summary.append(
            SummaryLine(kind="import", identifier=import_id, name=str(payload.get("name", "?")), detail=detail)
        )

    def _add_uploads(self) -> None:
        """Upload mất người dùng thì gỡ theo; upload còn scene/bản nhập khác dùng thì chỉ bỏ liên kết."""
        gone_projects = {str(row.values["project_id"]) for row in self.rows if row.table == "r2s_projects"}
        gone_imports = {str(row.values["import_id"]) for row in self.rows if row.table == "r2s_imports"}
        requested = set(self.request.upload_ids)
        known: set[str] = set()
        for row in self._select("r2s_uploads", "1=1 ORDER BY upload_id", ()):
            upload_id = str(row.values["upload_id"])
            known.add(upload_id)
            upload = json.loads(str(row.values["payload"]))
            linked = [str(project_id) for project_id in upload.get("project_ids", [])]
            removed = [project_id for project_id in linked if project_id in gone_projects]
            found = self.tx.execute("SELECT import_id FROM r2s_imports WHERE upload_id=?", (upload_id,)).fetchall()
            importers = [str(importer[0]) for importer in found]
            touched = removed or any(i in gone_imports for i in importers) or upload_id in requested
            if not touched:
                continue
            still_used = [p for p in linked if p not in gone_projects] + [i for i in importers if i not in gone_imports]
            if still_used:
                if upload_id in requested:
                    self.blockers.append(f"{upload_id}: còn được dùng bởi {', '.join(still_used)}")
                if removed:
                    self.unlinks.append(
                        UploadUnlink(
                            upload_id=upload_id,
                            removed_project_ids=removed,
                            original_project_ids=linked,
                            original_payload=str(row.values["payload"]),
                        )
                    )
                continue
            self.rows += [row] + self._select("r2s_upload_sessions", "upload_id=?", (upload_id,))
            self._add_item("artifact", upload_id)
            detail = f"{int(upload.get('size_bytes', 0)) / 1e6:.1f} MB, không còn scene hay bản nhập nào dùng"
            self.summary.append(
                SummaryLine(
                    kind="upload", identifier=upload_id, name=str(upload.get("original_name", "?")), detail=detail
                )
            )
        for upload_id in sorted(requested - known):
            self.blockers.append(f"{upload_id}: không tìm thấy upload")


def plan_deletion(context: DeletionContext, request: DeletionRequest) -> DeletionPlan:
    """Tính mọi thứ sẽ bị gỡ và lý do từ chối (nếu có); không sửa gì."""
    with context.database.transaction() as tx:
        return _Collector(context, tx, request).plan()


def _key(row: StoredRow) -> tuple[str, tuple[str | int, ...]]:
    """Mệnh đề WHERE theo khoá chính của dòng và giá trị bind tương ứng."""
    columns = _TABLE_COLUMNS[row.table][: _KEY_WIDTH.get(row.table, 1)]
    return " AND ".join(f"{column}=?" for column in columns), tuple(row.values[column] for column in columns)


def _audit(tx: RuntimeTransaction, action: str, line: SummaryLine, record: "DeletionRecord", actor: str | None) -> None:
    """Ghi nhật ký trong cùng transaction với thay đổi; `actor` trống khi là thao tác CLI của người vận hành."""
    entry_id = record.entry_id
    entry = AuditEntry(
        entry_id=uuid4().hex,
        at=datetime.now(UTC),
        user_id=actor,
        action=action,
        target=line.identifier,
        details={"name": line.name, "trash_entry": entry_id},
    )
    tx.execute(
        "INSERT INTO r2s_audit_log(entry_id, at, user_id, action, payload) VALUES (?, ?, ?, ?, ?)",
        (entry.entry_id, entry.at.isoformat(), actor, action, entry.model_dump_json()),
    )


def _locked_upload(tx: RuntimeTransaction, upload_id: str) -> UploadRecord:
    """Upload đang được giữ, đọc có khoá trong transaction ghi."""
    row = tx.execute("SELECT payload FROM r2s_uploads WHERE upload_id=?" + tx.lock_suffix(), (upload_id,)).fetchone()
    if row is None:
        raise RuntimeStateConflictError(f"Upload {upload_id} không còn; đọc lại trước khi gỡ/khôi phục")
    return UploadRecord.model_validate_json(row[0])


def _unlink_upload(tx: RuntimeTransaction, unlink: UploadUnlink) -> None:
    """Bỏ các project đã gỡ khỏi một upload còn scene khác dùng."""
    record = _locked_upload(tx, unlink.upload_id)
    kept = [project_id for project_id in record.project_ids if project_id not in unlink.removed_project_ids]
    payload = record.model_copy(update={"project_ids": kept}).model_dump_json()
    tx.execute("UPDATE r2s_uploads SET payload=? WHERE upload_id=?", (payload, unlink.upload_id))


def _relink_upload(tx: RuntimeTransaction, unlink: UploadUnlink) -> None:
    """Gắn lại các project vừa khôi phục vào upload.

    Upload không đổi gì từ lúc gỡ thì trả lại đúng payload cũ: record đời trước thiếu vài field mặc định, ghi lại qua
    model sẽ cho payload khác bytes. Đã có scene mới gắn vào thì giữ chúng ở cuối danh sách.
    """
    current = _locked_upload(tx, unlink.upload_id)
    original = UploadRecord.model_validate_json(unlink.original_payload)
    added = [project_id for project_id in current.project_ids if project_id not in original.project_ids]
    untouched = not added and current == original.model_copy(update={"project_ids": current.project_ids})
    merged = current.model_copy(update={"project_ids": [*original.project_ids, *added]})
    payload = unlink.original_payload if untouched else merged.model_dump_json()
    tx.execute("UPDATE r2s_uploads SET payload=? WHERE upload_id=?", (payload, unlink.upload_id))


def _delete_rows(tx: RuntimeTransaction, plan: DeletionPlan) -> None:
    for table in _DELETE_ORDER:
        for row in (row for row in plan.rows if row.table == table):
            where, parameters = _key(row)
            if tx.execute(f"DELETE FROM {table} WHERE {where}", parameters).rowcount != 1:
                raise RuntimeStateConflictError(f"Dòng {table} đã đổi; đọc lại trước khi gỡ")
    for unlink in plan.upload_unlinks:
        _unlink_upload(tx, unlink)


def context_from_settings(settings: Settings) -> DeletionContext:
    """Định vị DB, kho artifact, thư mục theo job và thùng rác của deployment này."""
    artifact_root = settings.artifact_root.expanduser().resolve()
    trash_root = settings.product_trash_root
    return DeletionContext(
        database=RuntimeDatabase(settings.database_url),
        resolver=runtime_resolver(settings),
        worker_root=settings.product_worker_root.expanduser().resolve(),
        rerun_dir=settings.product_rerun_recording_dir.expanduser().resolve(),
        trash_root=trash_root.expanduser().resolve() if trash_root else artifact_root.parent / "trash",
    )


def list_trash(database: RuntimeDatabase) -> list[DeletionRecord]:
    """Các mục đang nằm trong thùng rác, mới gỡ nhất trước."""
    with database.transaction() as tx:
        rows = tx.execute("SELECT payload FROM r2s_trash ORDER BY deleted_at DESC, entry_id").fetchall()
    return [DeletionRecord.model_validate_json(row[0]) for row in rows]


def get_trash_entry(database: RuntimeDatabase, entry_id: str) -> DeletionRecord:
    """Một mục thùng rác; không có (đã khôi phục/xoá hẳn hoặc ID sai) thì từ chối."""
    with database.transaction() as tx:
        row = tx.execute("SELECT payload FROM r2s_trash WHERE entry_id=?", (entry_id,)).fetchone()
    if row is None:
        raise DeletionRefusedError([f"{entry_id}: không có trong thùng rác"])
    return DeletionRecord.model_validate_json(row[0])


def _take_entry(tx: RuntimeTransaction, record: DeletionRecord) -> None:
    """Xoá dòng thùng rác trong transaction kết thúc mục đó; hai thao tác cùng lúc thì chỉ một bên thắng."""
    if tx.execute("DELETE FROM r2s_trash WHERE entry_id=?", (record.entry_id,)).rowcount != 1:
        raise RuntimeStateConflictError(f"Mục thùng rác {record.entry_id} vừa được xử lý ở nơi khác")


def apply_deletion(context: DeletionContext, request: DeletionRequest, actor: str | None = None) -> DeletionRecord:
    """Chuyển scene/bản nhập theo yêu cầu vào thùng rác; trả bản ghi của mục vừa tạo.

    Kế hoạch được tính lại trong chính transaction ghi, nên điều kiện từ chối được kiểm trên trạng thái mới nhất.
    """
    entry_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:6]}"
    with context.database.transaction(write=True) as tx:
        plan = _Collector(context, tx, request).plan()
        if plan.blockers:
            raise DeletionRefusedError(plan.blockers)
        record = DeletionRecord(entry_id=entry_id, created_at=datetime.now(UTC), deleted_by=actor, plan=plan)
        tx.execute(
            "INSERT INTO r2s_trash(entry_id, deleted_at, payload) VALUES (?, ?, ?)",
            (entry_id, record.created_at.isoformat(), record.model_dump_json()),
        )
        _delete_rows(tx, plan)
        for line in plan.summary:
            _audit(tx, f"{line.kind}.delete", line, record, actor)
    entry = context.entry_dir(entry_id)
    for item in plan.items:
        source = context.live_path(item)
        if source.exists():
            target = trash_path(entry, item)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
    return record


def _restore_row(tx: RuntimeTransaction, row: StoredRow) -> None:
    """Chèn lại một dòng; dòng đã có y nguyên thì bỏ qua, khác nội dung thì dừng."""
    columns = _TABLE_COLUMNS[row.table]
    where, parameters = _key(row)
    existing = tx.execute(f"SELECT {', '.join(columns)} FROM {row.table} WHERE {where}", parameters).fetchone()
    values = tuple(row.values[column] for column in columns)
    if existing is None:
        marks = ", ".join("?" for _ in columns)
        tx.execute(f"INSERT INTO {row.table}({', '.join(columns)}) VALUES ({marks})", values)
    elif tuple(existing) != values:
        raise RuntimeStateConflictError(f"{row.table} đã có dòng khác nội dung cho {parameters}")


def restore_deletion(context: DeletionContext, entry_id: str, actor: str | None = None) -> DeletionRecord:
    """Đưa một mục thùng rác trở lại: thư mục trước, dòng DB sau, để DB không trỏ tới file chưa có.

    Deployment có kho file thì file thiếu trên máy này không phải lỗi: artifact được tải lại từ kho khi cần.
    """
    record = get_trash_entry(context.database, entry_id)
    entry = context.entry_dir(entry_id)
    moves: list[tuple[Path, Path]] = []
    problems: list[str] = []
    for item in record.plan.items:
        source, target = trash_path(entry, item), context.live_path(item)
        if source.exists() and target.exists():
            problems.append(f"{item.kind}/{item.name}: vị trí đang dùng đã có dữ liệu khác")
        elif source.exists():
            moves.append((source, target))
        elif not target.exists() and context.resolver.remote is None:
            problems.append(f"{item.kind}/{item.name}: không còn trong thùng rác lẫn vị trí đang dùng")
    if problems:
        raise DeletionRefusedError(problems)
    for source, target in moves:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
    with context.database.transaction(write=True) as tx:
        _take_entry(tx, record)
        for table in _TABLE_COLUMNS:
            for row in (row for row in record.plan.rows if row.table == table):
                _restore_row(tx, row)
        for unlink in record.plan.upload_unlinks:
            _relink_upload(tx, unlink)
        for line in record.plan.summary:
            _audit(tx, f"{line.kind}.restore", line, record, actor)
    shutil.rmtree(entry, ignore_errors=True)
    return record


@dataclass(frozen=True)
class PurgeResult:
    """Những gì một lần xoá hẳn đã xoá."""

    local_bytes: int
    remote_objects: int


def purge_deletion(context: DeletionContext, entry_id: str, actor: str | None = None) -> PurgeResult:
    """Xoá hẳn một mục thùng rác, không khôi phục được: kho file (nếu có) → thư mục trên máy → dòng thùng rác.

    Dòng thùng rác bị xoá sau cùng, nên dừng giữa chừng thì mục vẫn còn trong thùng rác và xoá lại là xong phần còn lại.
    """
    record = get_trash_entry(context.database, entry_id)
    remote = context.resolver.remote
    removed = 0
    if remote is not None:
        removed = sum(remote.delete_tree(f"jobs/{_safe(name)}") for name in record.plan.remote_namespaces)
    entry = context.entry_dir(entry_id)
    size = _tree_size([entry])
    shutil.rmtree(entry, ignore_errors=True)
    with context.database.transaction(write=True) as tx:
        _take_entry(tx, record)
        for line in record.plan.summary:
            _audit(tx, f"{line.kind}.purge", line, record, actor)
    return PurgeResult(local_bytes=size, remote_objects=removed)


def import_legacy_entry(context: DeletionContext, directory: Path) -> DeletionRecord:
    """Đưa một lần gỡ của phiên bản trước (thư mục có `deletion_record.json`) vào thùng rác hiện tại.

    Sau đó mục này khôi phục/xoá hẳn như mọi mục khác. Chỉ nhận lần gỡ đã hoàn tất.
    """
    path = directory / RECORD_NAME
    if not path.is_file():
        raise DeletionRefusedError([f"{directory.name}: không phải thư mục của một lần gỡ (thiếu {RECORD_NAME})"])
    record = DeletionRecord.model_validate_json(path.read_text(encoding="utf-8"))
    if record.entry_id != directory.name or record.state != "removed":
        raise DeletionRefusedError([f"{directory.name}: bản ghi không khớp thư mục hoặc lần gỡ chưa hoàn tất"])
    record = record.model_copy(update={"plan": _with_namespaces(record.plan)})
    target = context.entry_dir(record.entry_id)
    if directory.resolve() != target.resolve():
        if target.exists():
            raise DeletionRefusedError([f"{record.entry_id}: thùng rác đã có thư mục cùng tên"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(directory), str(target))
    with context.database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_trash(entry_id, deleted_at, payload) VALUES (?, ?, ?)",
            (record.entry_id, record.created_at.isoformat(), record.model_dump_json()),
        )
    (target / RECORD_NAME).unlink(missing_ok=True)
    return record


def _with_namespaces(plan: DeletionPlan) -> DeletionPlan:
    """Bản ghi cũ chưa có danh sách namespace cho kho file: suy từ các mục artifact đã dời."""
    if plan.remote_namespaces:
        return plan
    return plan.model_copy(update={"remote_namespaces": [item.name for item in plan.items if item.kind == "artifact"]})
