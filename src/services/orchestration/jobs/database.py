"""Transaction runtime: SQLite local hoặc PostgreSQL, không chứa binary artifact.

SQL chỉ chứa hằng số nội bộ; mọi giá trị đi qua bind parameters. Connection không
chia sẻ giữa các thread của FastAPI. Không mở database khi import module.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
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


_TABLES = (
    "CREATE TABLE IF NOT EXISTS r2s_projects (project_id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS r2s_jobs (
        job_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES r2s_projects(project_id),
        version INTEGER NOT NULL, manifest_ref TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS r2s_job_events (
        job_id TEXT NOT NULL REFERENCES r2s_jobs(job_id), version INTEGER NOT NULL,
        payload TEXT NOT NULL, PRIMARY KEY(job_id, version))""",
    "CREATE INDEX IF NOT EXISTS r2s_jobs_by_project ON r2s_jobs(project_id)",
    # Bảng cộng thêm (không đổi bảng cũ): video upload chờ được chọn để tạo scene.
    "CREATE TABLE IF NOT EXISTS r2s_uploads (upload_id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
)


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
        self._initialize()

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
        with self.transaction(write=True) as tx:
            if self.postgres:
                tx.execute("SELECT pg_advisory_xact_lock(hashtext('real2sim.runtime.schema'))")
            tx.execute(
                "CREATE TABLE IF NOT EXISTS r2s_schema (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)"
            )
            tx.execute("INSERT INTO r2s_schema(id, version) VALUES (1, 1) ON CONFLICT(id) DO NOTHING")
            row = tx.execute("SELECT version FROM r2s_schema WHERE id=1").fetchone()
            if row != (1,):
                raise RuntimeError("Runtime database schema chưa được hỗ trợ; cần migration trước khi khởi động")
            for statement in _TABLES:
                tx.execute(statement)
