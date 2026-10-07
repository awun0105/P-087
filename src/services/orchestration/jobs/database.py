"""Transaction runtime: SQLite local hoặc PostgreSQL, không chứa binary artifact.

SQL chỉ chứa hằng số nội bộ; mọi giá trị đi qua bind parameters. Connection không
chia sẻ giữa các thread của FastAPI. Không mở database khi import module.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Protocol, cast


class RuntimeStateConflictError(RuntimeError):
    """State đã đổi ở process khác; caller phải đọc lại trước khi retry command."""


class SqlCursor(Protocol):
    """Phần DB-API dùng chung giữa sqlite3 và psycopg."""

    rowcount: int

    def fetchone(self) -> tuple | None: ...

    def fetchall(self) -> list[tuple]: ...


class SqlConnection(Protocol):
    """Connection thuộc một transaction, không giữ trong registry singleton."""

    def execute(self, query: str, parameters: tuple = ()) -> SqlCursor: ...

    def close(self) -> None: ...


class RuntimeTransaction:
    """SQL adapter nhỏ; business state không nằm trong driver."""

    def __init__(self, connection: SqlConnection, postgres: bool) -> None:
        self.connection = connection
        self.postgres = postgres

    def execute(self, statement: str, parameters: tuple = ()) -> SqlCursor:
        """Statements nội bộ dùng ?, chuyển placeholder cho PostgreSQL."""
        return self.connection.execute(statement.replace("?", "%s") if self.postgres else statement, parameters)

    def lock_suffix(self) -> str:
        """SQLite dùng BEGIN IMMEDIATE; PostgreSQL khóa row của entity đang sửa."""
        return " FOR UPDATE" if self.postgres else ""


#: Migration có thứ tự (ADR 0003 §5): mỗi bước chỉ CREATE/ALTER cộng thêm, chạy trong
#: transaction bootstrap; không drop/reset. DB có version mới hơn code bị từ chối.
MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            "CREATE TABLE IF NOT EXISTS r2s_projects (project_id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
            """CREATE TABLE IF NOT EXISTS r2s_jobs (
                job_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES r2s_projects(project_id),
                version INTEGER NOT NULL, manifest_ref TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS r2s_job_events (
                job_id TEXT NOT NULL REFERENCES r2s_jobs(job_id), version INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(job_id, version))""",
            "CREATE INDEX IF NOT EXISTS r2s_jobs_by_project ON r2s_jobs(project_id)",
        ),
    ),
    (
        # Studio MVP: các bảng này từng được tạo `IF NOT EXISTS` khi schema còn v1, nên
        # migration giữ `IF NOT EXISTS` để DB cũ nâng lên v2 mà không lỗi, không mất dữ liệu.
        2,
        (
            # Video upload chờ được chọn để tạo scene.
            "CREATE TABLE IF NOT EXISTS r2s_uploads (upload_id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
            # Cấu hình máy do worker tự đo (GPU/VRAM/CPU/RAM/đĩa).
            "CREATE TABLE IF NOT EXISTS r2s_workers (worker_id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
            # Phiên upload thẳng lên kho file (ADR 0003), UPLOADING→READY.
            "CREATE TABLE IF NOT EXISTS r2s_upload_sessions (upload_id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
        ),
    ),
    (
        # Đăng nhập hai role (ADR 0003 §3): tài khoản, mã mời, phiên, nhật ký thao tác.
        3,
        (
            """CREATE TABLE r2s_users (
                user_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, payload TEXT NOT NULL)""",
            "CREATE TABLE r2s_invites (code_hash TEXT PRIMARY KEY, payload TEXT NOT NULL)",
            """CREATE TABLE r2s_sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES r2s_users(user_id),
                expires_at TEXT NOT NULL, payload TEXT NOT NULL)""",
            """CREATE TABLE r2s_audit_log (
                entry_id TEXT PRIMARY KEY, at TEXT NOT NULL, user_id TEXT, action TEXT NOT NULL,
                payload TEXT NOT NULL)""",
            "CREATE INDEX r2s_audit_by_user ON r2s_audit_log(user_id, at)",
        ),
    ),
    (
        # Scene 3DGS người dùng tải lên, chỉ xem/chỉnh sửa (ADR 0004 §3, gói 5).
        4,
        ("CREATE TABLE r2s_imports (import_id TEXT PRIMARY KEY, upload_id TEXT NOT NULL, payload TEXT NOT NULL)",),
    ),
    (
        # Yêu cầu dựng lại tập vật của scene (chạy lại tách theo vật / dùng hộp): API ghi, worker nhận.
        # Nằm trong DB chung để API và worker ở hai máy khác nhau vẫn thấy nhau; mỗi job giữ yêu cầu gần nhất.
        5,
        (
            """CREATE TABLE r2s_scene_requests (
                job_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL)""",
            "CREATE INDEX r2s_scene_requests_by_status ON r2s_scene_requests(status)",
        ),
    ),
    (
        # Thùng rác scene: bản ghi của mỗi lần gỡ (dòng DB đã gỡ + namespace file) để khôi phục hoặc xoá hẳn.
        # Nằm trong DB vì đĩa của API trên cloud không bền; file trên kho S3/R2 chỉ bị xoá khi xoá hẳn.
        6,
        ("CREATE TABLE r2s_trash (entry_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL, payload TEXT NOT NULL)",),
    ),
    (
        # Observation tài nguyên bind job revision; JobManifest vẫn sở hữu queue/lifecycle.
        7,
        (
            "CREATE TABLE r2s_resource_waits (job_id TEXT PRIMARY KEY REFERENCES r2s_jobs(job_id) ON DELETE CASCADE, payload TEXT NOT NULL)",
        ),
    ),
    (
        # Giữ chỗ tài nguyên: một dòng cho mỗi worker đang chạy job (không phải lifecycle của job).
        # Số đo tài nguyên theo lần chạy công cụ: lịch sử của máy, không cascade theo job để còn
        # dùng cho ước lượng sau khi scene bị xoá.
        8,
        (
            "CREATE TABLE r2s_resource_reservations (worker_id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
            "CREATE TABLE r2s_resource_usage (usage_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, "
            "recorded_at TEXT NOT NULL, payload TEXT NOT NULL)",
            "CREATE INDEX r2s_resource_usage_job ON r2s_resource_usage(job_id)",
        ),
    ),
    (
        # Lịch sử validation bất biến theo attempt; selection CAS trỏ tới một run cụ thể.
        9,
        (
            """CREATE TABLE r2s_validation_runs (
                run_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                candidate_checksum TEXT NOT NULL,
                config_checksum TEXT NOT NULL,
                attempt INTEGER NOT NULL CHECK(attempt > 0),
                status TEXT NOT NULL,
                run_checksum TEXT NOT NULL,
                payload TEXT NOT NULL,
                UNIQUE(job_id, candidate_checksum, config_checksum, attempt),
                UNIQUE(run_id, job_id, candidate_checksum, config_checksum))""",
            "CREATE INDEX r2s_validation_runs_identity ON r2s_validation_runs(job_id, candidate_checksum, config_checksum, attempt)",
            """CREATE TABLE r2s_validation_selections (
                job_id TEXT NOT NULL,
                candidate_checksum TEXT NOT NULL,
                config_checksum TEXT NOT NULL,
                run_id TEXT NOT NULL,
                report_checksum TEXT NOT NULL,
                generation INTEGER NOT NULL CHECK(generation > 0),
                selection_checksum TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(job_id, candidate_checksum, config_checksum),
                FOREIGN KEY(run_id, job_id, candidate_checksum, config_checksum)
                    REFERENCES r2s_validation_runs(run_id, job_id, candidate_checksum, config_checksum))""",
        ),
    ),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1][0]

#: DB đã kiểm/chạy migration trong tiến trình này. API tạo RuntimeDatabase mỗi request;
#: chỉ lần đầu mới cần transaction bootstrap (tránh khóa ghi + vòng mạng mỗi request).
_READY: set[str] = set()
_READY_LOCK = Lock()


class RuntimeDatabase:
    """Persistence vận hành v1; nâng schema phải có migration, không tự drop/reset."""

    def __init__(self, url: str) -> None:
        self._url = url
        self.postgres = url.startswith(("postgresql://", "postgres://"))
        self._sqlite_path: Path | None = None
        if not self.postgres:
            if not url.startswith("sqlite:///"):
                raise ValueError("DATABASE_URL chỉ hỗ trợ sqlite:/// hoặc postgresql://")
            value = url.removeprefix("sqlite:///")
            if not value or value == ":memory:" or "?" in value:
                raise ValueError("Runtime database cần file SQLite bền vững, không dùng memory/URI options")
            self._sqlite_path = Path(value).expanduser().resolve()
            self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with _READY_LOCK:
            if url not in _READY:
                self._initialize()
                _READY.add(url)

    def _connect(self) -> SqlConnection:
        if self.postgres:
            try:
                import psycopg
            except ImportError as error:
                raise RuntimeError("PostgreSQL cần psycopg 3; cài dependency runtime trước khi khởi động") from error
            return cast(SqlConnection, psycopg.connect(self._url, autocommit=True, connect_timeout=10))
        connection = sqlite3.connect(str(self._sqlite_path), timeout=30, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        return cast(SqlConnection, connection)

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[RuntimeTransaction]:
        """Rollback mọi lỗi tại DB process boundary rồi giữ nguyên exception cause."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write and not self.postgres else "BEGIN")
            try:
                yield RuntimeTransaction(connection, self.postgres)
            except BaseException:
                # Kể cả KeyboardInterrupt phải nhả transaction; không swallow lỗi.
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")
        finally:
            connection.close()

    def _initialize(self) -> None:
        """Tạo bảng version rồi chạy các migration còn thiếu trong một transaction có khóa."""
        with self.transaction(write=True) as tx:
            if self.postgres:
                tx.execute("SELECT pg_advisory_xact_lock(hashtext('real2sim.runtime.schema'))")
            tx.execute(
                "CREATE TABLE IF NOT EXISTS r2s_schema (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)"
            )
            tx.execute("INSERT INTO r2s_schema(id, version) VALUES (1, 0) ON CONFLICT(id) DO NOTHING")
            row = tx.execute("SELECT version FROM r2s_schema WHERE id=1").fetchone()
            current = row[0] if row else 0
            if current > LATEST_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Runtime database ở schema v{current}, code chỉ hỗ trợ tới v{LATEST_SCHEMA_VERSION}; "
                    "cập nhật code trước khi khởi động"
                )
            for version, statements in MIGRATIONS:
                if version <= current:
                    continue
                for statement in statements:
                    tx.execute(statement)
                tx.execute("UPDATE r2s_schema SET version=? WHERE id=1", (version,))

    def schema_version(self) -> int:
        """Version schema hiện tại (dùng cho health/chẩn đoán)."""
        with self.transaction() as tx:
            row = tx.execute("SELECT version FROM r2s_schema WHERE id=1").fetchone()
        return int(row[0]) if row else 0

    def ping(self) -> None:
        """Truy vấn nhẹ; `/health` dùng để kiểm DB và giữ Supabase Free không tạm dừng."""
        with self.transaction() as tx:
            tx.execute("SELECT 1").fetchone()
