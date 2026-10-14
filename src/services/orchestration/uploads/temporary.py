"""Bounded lifetime for uploads abandoned before scene creation."""

import json
import logging
import re
import shutil
from datetime import UTC, datetime, timedelta

from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError, RuntimeTransaction
from src.services.orchestration.uploads.models import UploadSession

logger = logging.getLogger(__name__)
UPLOAD_TTL = timedelta(hours=24)


def register_temporary(tx: RuntimeTransaction, upload_id: str, owner_id: str) -> None:
    tx.execute(
        "INSERT INTO r2s_temporary_uploads(upload_id,owner_id,expires_at) VALUES (?,?,?) "
        "ON CONFLICT(upload_id) DO NOTHING",
        (upload_id, owner_id, (datetime.now(UTC) + UPLOAD_TTL).isoformat()),
    )


def _mentions(value: object, upload_id: str) -> bool:
    if isinstance(value, str):
        return (
            value == upload_id
            or f"artifact://jobs/{upload_id}/" in value
            or f'"{upload_id}"' in value  # Trash records also embed immutable rows as JSON strings.
        )
    if isinstance(value, dict):
        return any(_mentions(item, upload_id) for item in value.values())
    if isinstance(value, list):
        return any(_mentions(item, upload_id) for item in value)
    return False


class TemporaryUploadService:
    def __init__(self, database: RuntimeDatabase, resolver: ArtifactResolver) -> None:
        self.database = database
        self.resolver = resolver

    def reserve(self, upload_ids: list[str]) -> None:
        """Protect source bytes while Run/import is being accepted, including a lost HTTP response."""
        with self.database.transaction(write=True) as tx:
            for upload_id in sorted(set(upload_ids)):
                row = tx.execute(
                    "SELECT deleting FROM r2s_temporary_uploads WHERE upload_id=?" + tx.lock_suffix(), (upload_id,)
                ).fetchone()
                if row is not None and row[0]:
                    raise RuntimeStateConflictError("Upload đang được dọn; hãy tải lại file")
                if row is None and not (
                    tx.execute("SELECT 1 FROM r2s_uploads WHERE upload_id=?", (upload_id,)).fetchone()
                    or tx.execute("SELECT 1 FROM r2s_input_uploads WHERE upload_id=?", (upload_id,)).fetchone()
                ):
                    raise RuntimeStateConflictError("Upload không còn tồn tại; hãy tải lại file")
                tx.execute(
                    "UPDATE r2s_temporary_uploads SET protected_until=? WHERE upload_id=?",
                    ((datetime.now(UTC) + UPLOAD_TTL).isoformat(), upload_id),
                )

    def renew(self, upload_ids: list[str], owner_id: str) -> None:
        with self.database.transaction(write=True) as tx:
            for upload_id in sorted(set(upload_ids)):
                row = tx.execute(
                    "SELECT owner_id,deleting FROM r2s_temporary_uploads WHERE upload_id=?" + tx.lock_suffix(),
                    (upload_id,),
                ).fetchone()
                if row is None:
                    stored = tx.execute(
                        "SELECT payload FROM r2s_input_uploads WHERE upload_id=?", (upload_id,)
                    ).fetchone()
                    if stored is None:
                        stored = tx.execute(
                            "SELECT payload FROM r2s_uploads WHERE upload_id=?", (upload_id,)
                        ).fetchone()
                    if stored is None:
                        continue
                    record = json.loads(stored[0])
                    actor = record.get("uploaded_by")
                    recorded_owner = actor["user_id"] if actor else "anonymous"
                    if recorded_owner != owner_id or self._retained(tx, upload_id, self._assemblies(tx, upload_id)):
                        continue
                    register_temporary(tx, upload_id, owner_id)
                    continue
                if row[0] != owner_id:
                    raise PermissionError("Chỉ được dọn upload của chính bạn")
                if row[1]:
                    raise RuntimeStateConflictError("Upload đã hết phiên; hãy tải lại file")
                tx.execute(
                    "UPDATE r2s_temporary_uploads SET expires_at=? WHERE upload_id=?",
                    ((datetime.now(UTC) + UPLOAD_TTL).isoformat(), upload_id),
                )

    def discard(self, upload_ids: list[str], owner_id: str) -> list[str]:
        with self.database.transaction(write=True) as tx:
            for upload_id in sorted(set(upload_ids)):
                row = tx.execute(
                    "SELECT owner_id FROM r2s_temporary_uploads WHERE upload_id=?" + tx.lock_suffix(), (upload_id,)
                ).fetchone()
                if row is not None and row[0] != owner_id:
                    raise PermissionError("Chỉ được dọn upload của chính bạn")
                tx.execute(
                    "UPDATE r2s_temporary_uploads SET expires_at=? WHERE upload_id=?",
                    (datetime.now(UTC).isoformat(), upload_id),
                )
        return [upload_id for upload_id in set(upload_ids) if self._purge(upload_id, datetime.now(UTC))]

    def purge_expired(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now(UTC)
        with self.database.transaction() as tx:
            rows = tx.execute(
                "SELECT upload_id FROM r2s_temporary_uploads WHERE expires_at<=? ORDER BY expires_at LIMIT 100",
                (now.isoformat(),),
            ).fetchall()
        deleted = []
        for row in rows:
            try:
                if self._purge(row[0], now):
                    deleted.append(row[0])
            except (OSError, ValueError, RuntimeStateConflictError) as error:
                logger.warning("Không dọn được upload tạm %s: %s", row[0], type(error).__name__)
        return deleted

    @staticmethod
    def _assemblies(tx: RuntimeTransaction, upload_id: str) -> set[str]:
        return {
            row[0]
            for row in tx.execute("SELECT assembly_id,payload FROM r2s_input_assemblies").fetchall()
            if _mentions(json.loads(row[1]), upload_id)
        }

    @staticmethod
    def _retained(tx: RuntimeTransaction, upload_id: str, assemblies: set[str]) -> bool:
        for table in ("r2s_projects", "r2s_imports", "r2s_input_runs", "r2s_trash"):
            for row in tx.execute(f"SELECT payload FROM {table}").fetchall():
                if _mentions(json.loads(row[0]), upload_id):
                    return True
        for assembly_id in assemblies:
            if tx.execute("SELECT 1 FROM r2s_input_runs WHERE assembly_id=?", (assembly_id,)).fetchone():
                return True
        for table in ("r2s_uploads", "r2s_input_uploads"):
            row = tx.execute(f"SELECT payload FROM {table} WHERE upload_id=?", (upload_id,)).fetchone()
            if row is not None and json.loads(row[0]).get("project_ids"):
                return True
        return False

    def _purge(self, upload_id: str, now: datetime) -> bool:
        if not re.fullmatch(r"upload-[a-zA-Z0-9_-]+", upload_id):
            raise ValueError("Invalid temporary upload namespace")
        with self.database.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT expires_at,protected_until FROM r2s_temporary_uploads WHERE upload_id=?" + tx.lock_suffix(),
                (upload_id,),
            ).fetchone()
            if row is None or datetime.fromisoformat(row[0]) > now:
                return False
            assemblies = self._assemblies(tx, upload_id)
            if self._retained(tx, upload_id, assemblies):
                tx.execute("DELETE FROM r2s_temporary_uploads WHERE upload_id=?", (upload_id,))
                return False
            if row[1] and datetime.fromisoformat(row[1]) > now:
                return False
            tx.execute("UPDATE r2s_temporary_uploads SET deleting=1 WHERE upload_id=?", (upload_id,))
            session_row = tx.execute(
                "SELECT payload FROM r2s_upload_sessions WHERE upload_id=?", (upload_id,)
            ).fetchone()

        # Files first, metadata last: a failed remote/local delete remains retryable.
        directory = self.resolver.artifact_root / "jobs" / upload_id
        if directory.is_symlink() or directory.resolve() != directory.absolute():
            raise ValueError("Refusing symlinked upload namespace")
        remote = self.resolver.remote
        if remote is not None:
            if session_row is not None:
                session = UploadSession.model_validate_json(session_row[0])
                if session.status == "UPLOADING":
                    remote.abort_upload(self.resolver.relative_key(session.artifact_uri), session.multipart_id)
            remote.delete_tree(f"jobs/{upload_id}")
        if directory.exists():
            shutil.rmtree(directory)
        with self.database.transaction(write=True) as tx:
            for assembly_id in self._assemblies(tx, upload_id):
                tx.execute("DELETE FROM r2s_input_assembly_heads WHERE assembly_id=?", (assembly_id,))
                tx.execute("DELETE FROM r2s_input_resolutions WHERE assembly_id=?", (assembly_id,))
                tx.execute("DELETE FROM r2s_input_assemblies WHERE assembly_id=?", (assembly_id,))
            for table in ("r2s_input_uploads", "r2s_uploads", "r2s_upload_sessions", "r2s_temporary_uploads"):
                tx.execute(f"DELETE FROM {table} WHERE upload_id=?", (upload_id,))
        return True
