"""Gỡ scene khỏi Studio theo cách khôi phục được: dòng DB và thư mục của scene chuyển vào thùng rác.

Studio chưa có policy lưu trữ (PRD NFR-05: thời gian lưu do Chủ sở hữu sản phẩm xác nhận; STUDIO_UX_SPEC Q7), nên đây
là thao tác vận hành chạy bằng CLI (`delete_cli`), không phải tính năng của UI/API.

Một scene = project + các job của nó. Gỡ scene kéo theo journal và yêu cầu dựng lại vật của job, thư mục artifact của
job/project, thư mục làm việc của worker và bản ghi Rerun. Upload nguồn chỉ bị gỡ khi không còn scene hay bản nhập nào
dùng nó. Scene nhập (import) được gỡ theo cùng cách.

Thứ tự: ghi `deletion_record.json` (đủ để khôi phục) → xoá các dòng DB trong một transaction → chuyển thư mục vào thùng
rác. Dừng giữa chừng chỉ để lại thư mục mồ côi, DB không bao giờ trỏ tới file đã mất. `restore_deletion` làm ngược lại;
chỉ `purge_deletion` mới xoá hẳn.

Từ chối (fail closed): job đang chờ worker hoặc đang chạy, bản nhập đang đóng gói, yêu cầu dựng lại vật đang chờ/chạy,
scene đã có bản phát hành (PRD US-06) khi chưa cho phép rõ ràng, và deployment dùng kho file S3 (gỡ cục bộ sẽ để lại
object trên kho).
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

from src.models.contracts.artifacts import ArtifactRef, Identifier
from src.models.contracts.manifests import JobManifest, JobStatus, StageId
from src.services.orchestration.artifacts import ArtifactResolver, ArtifactStoreError
from src.services.orchestration.auth.models import AuditEntry
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError, RuntimeTransaction
from src.services.orchestration.jobs.progress import metric_confirmation_stage
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
    size_bytes: int
    blockers: list[str]


class DeletionRecord(BaseModel):
    """Bản ghi của một lần gỡ, nằm trong thư mục thùng rác của lần đó.

    `planned`: đã ghi bản ghi, DB/thư mục có thể mới gỡ một phần. `removed`: gỡ xong. `restored`: đã khôi phục.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    entry_id: str
    created_at: datetime
    state: Literal["planned", "removed", "restored"]
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


def _audit(tx: RuntimeTransaction, action: str, line: SummaryLine, entry_id: str) -> None:
    """Ghi nhật ký trong cùng transaction với thay đổi; `user_id` trống vì đây là thao tác CLI của người vận hành."""
    entry = AuditEntry(
        entry_id=uuid4().hex,
        at=datetime.now(UTC),
        user_id=None,
        action=action,
        target=line.identifier,
        details={"name": line.name, "trash_entry": entry_id},
    )
    tx.execute(
        "INSERT INTO r2s_audit_log(entry_id, at, user_id, action, payload) VALUES (?, ?, ?, ?, ?)",
        (entry.entry_id, entry.at.isoformat(), None, action, entry.model_dump_json()),
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


def _write_record(entry: Path, record: DeletionRecord) -> None:
    """Ghi nguyên tử để bản ghi không bao giờ nằm dở dang trên đĩa."""
    temporary = entry / f".{RECORD_NAME}.tmp"
    temporary.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(entry / RECORD_NAME)


def load_record(entry: Path) -> DeletionRecord:
    """Đọc bản ghi của một thư mục thùng rác; thư mục không do thao tác này tạo thì từ chối."""
    path = entry / RECORD_NAME
    if not path.is_file():
        raise DeletionRefusedError([f"{entry.name}: không phải thư mục của một lần gỡ (thiếu {RECORD_NAME})"])
    record = DeletionRecord.model_validate_json(path.read_text(encoding="utf-8"))
    if record.entry_id != entry.name:
        raise DeletionRefusedError([f"{entry.name}: bản ghi thuộc lần gỡ khác ({record.entry_id})"])
    return record


def apply_deletion(context: DeletionContext, request: DeletionRequest, trash_root: Path) -> DeletionRecord:
    """Gỡ theo yêu cầu; thư mục của lần gỡ là `trash_root / record.entry_id`.

    Kế hoạch được tính lại trong chính transaction ghi, nên điều kiện từ chối được kiểm trên trạng thái mới nhất.
    """
    if context.resolver.remote is not None:
        raise DeletionRefusedError(["deployment dùng kho file S3: gỡ cục bộ sẽ để lại object trên kho"])
    entry = trash_root / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:6]}"
    created = False
    try:
        with context.database.transaction(write=True) as tx:
            plan = _Collector(context, tx, request).plan()
            if plan.blockers:
                raise DeletionRefusedError(plan.blockers)
            record = DeletionRecord(entry_id=entry.name, created_at=datetime.now(UTC), state="planned", plan=plan)
            entry.mkdir(parents=True)
            created = True
            _write_record(entry, record)
            _delete_rows(tx, plan)
            for line in plan.summary:
                _audit(tx, f"{line.kind}.delete", line, entry.name)
    except BaseException:
        # Transaction đã rollback: không có gì bị gỡ nên không để lại thư mục thùng rác rỗng gây hiểu nhầm.
        if created:
            shutil.rmtree(entry, ignore_errors=True)
        raise
    for item in plan.items:
        source = context.live_path(item)
        if source.exists():
            target = trash_path(entry, item)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
    record = record.model_copy(update={"state": "removed"})
    _write_record(entry, record)
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


def restore_deletion(context: DeletionContext, entry: Path) -> DeletionRecord:
    """Đưa scene đã gỡ trở lại: thư mục trước, dòng DB sau, để DB không trỏ tới file chưa có."""
    record = load_record(entry)
    if record.state == "restored":
        raise DeletionRefusedError([f"{entry.name}: đã khôi phục trước đó"])
    moves: list[tuple[Path, Path]] = []
    problems: list[str] = []
    for item in record.plan.items:
        source, target = trash_path(entry, item), context.live_path(item)
        if source.exists() and target.exists():
            problems.append(f"{item.kind}/{item.name}: vị trí đang dùng đã có dữ liệu khác")
        elif source.exists():
            moves.append((source, target))
        elif not target.exists():
            problems.append(f"{item.kind}/{item.name}: không còn trong thùng rác lẫn vị trí đang dùng")
    if problems:
        raise DeletionRefusedError(problems)
    for source, target in moves:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
    with context.database.transaction(write=True) as tx:
        for table in _TABLE_COLUMNS:
            for row in (row for row in record.plan.rows if row.table == table):
                _restore_row(tx, row)
        for unlink in record.plan.upload_unlinks:
            _relink_upload(tx, unlink)
        for line in record.plan.summary:
            _audit(tx, f"{line.kind}.restore", line, entry.name)
    record = record.model_copy(update={"state": "restored"})
    _write_record(entry, record)
    return record


def purge_deletion(entry: Path) -> int:
    """Xoá hẳn một lần gỡ khỏi thùng rác; trả dung lượng thư mục đã xoá (byte)."""
    record = load_record(entry)
    if record.state == "planned":
        raise DeletionRefusedError([f"{entry.name}: lần gỡ chưa hoàn tất; chạy restore rồi gỡ lại"])
    size = _tree_size([entry])
    shutil.rmtree(entry)
    return size
