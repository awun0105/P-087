"""Disposable, revision-fenced Studio workspaces backed by private SQLite and artifacts."""

import fcntl
import re
import secrets
import shutil
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict

from src.config import Settings
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.auth import AuthService
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.projects.models import DemoBaseline
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.samples.bundle import DemoLibrary, DemoUnavailableError
from src.services.orchestration.samples.session_context import DemoRuntime
from src.services.orchestration.samples.snapshot import copy_artifact_graph
from src.services.orchestration.samples.workspace import load_workspace

_TOKEN = re.compile(r"[a-f0-9]{32}")
# ponytail: keep at most 32 runtime handles; every request still checks the descriptor and lifetime.
_runtimes: OrderedDict[str, DemoRuntime] = OrderedDict()
_runtime_lock = Lock()


class DemoSessionUnavailableError(ValueError):
    """The capability is unknown, closed or expired."""


class DemoSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    sample_id: str
    job_id: str
    project_id: str
    source_revision: str
    actor_id: str
    created_at: AwareDatetime
    expires_at: AwareDatetime
    protected_uris: list[str] = []


class _SessionCreation(BaseModel):
    session_id: str
    created_at: AwareDatetime


def session_root(settings: Settings) -> Path:
    """Use the same filesystem as the immutable artifact store for cheap snapshots."""
    return settings.artifact_root.expanduser().resolve().parent / "demo_sessions"


def session_path(settings: Settings, session_id: str) -> Path:
    if _TOKEN.fullmatch(session_id) is None:
        raise DemoSessionUnavailableError("Phiên demo không hợp lệ")
    return session_root(settings) / session_id


def session_settings(settings: Settings, session_id: str) -> Settings:
    root = session_path(settings, session_id)
    return settings.model_copy(
        update={
            "database_url": f"sqlite:///{root / 'runtime.db'}",
            "artifact_root": root / "artifacts",
            "product_worker_root": root / "workers",
            "product_rerun_recording_dir": root / "recordings",
            "product_demo_dir": root / "library",
            "product_trash_root": root / "trash",
            "auth_required": False,
            "artifact_s3_bucket": None,
            "product_fixture_mode": False,
        }
    )


def _registry(settings: Settings, source: ProjectRegistry) -> ProjectRegistry:
    return ProjectRegistry(
        fixture_root=source.fixture_root,
        runtime_root=settings.artifact_root,
        database=RuntimeDatabase(settings.database_url),
        execution_profile=source.execution_profile,
        runtime_from_workers=False,
        processing_config_checksum=source.processing_config_checksum,
        job_seed=source.job_seed,
    )


def _create_session(settings: Settings, registry: ProjectRegistry, sample_id: str) -> DemoSession:
    """Clone the frozen published workspace; never read the source job's current state."""
    bundle = DemoLibrary(settings.product_demo_dir).bundle(sample_id)
    snapshot = load_workspace(bundle)
    job, project, head = snapshot.job, snapshot.project, snapshot.head
    job_id = job.job_id
    resolver = ArtifactResolver(bundle.root / "workspace" / "artifacts")
    session_id = uuid4().hex
    root = session_path(settings, session_id)
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    creating = _SessionCreation(session_id=session_id, created_at=datetime.now(UTC))
    (root / "initializing.json").write_text(creating.model_dump_json())
    ownership = (root / "session.lock").open("a")
    fcntl.flock(ownership, fcntl.LOCK_SH)
    private_settings = session_settings(settings, session_id)
    try:
        private = _registry(private_settings, registry)
        assert private.persistence is not None
        copy_artifact_graph(resolver, private.runtime_resolver, snapshot.files)
        recording = bundle.root / "workspace" / "recordings" / f"{job_id}.rrd"
        if recording.is_file():
            private_settings.product_rerun_recording_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(recording, private_settings.product_rerun_recording_dir / recording.name)
        actor = AuthService(private.persistence.database).create_user(
            f"{session_id}@demo.invalid", "Khách thử mẫu", secrets.token_urlsafe(32), "reviewer"
        )
        private.persistence.save_project(
            project.model_copy(
                update={
                    "demo_baseline": DemoBaseline(
                        job_id=job_id,
                        scene_revision=head.scene_revision,
                        marked_at=datetime.now(UTC),
                    )
                }
            )
        )
        draft = job
        reference = private.lifecycle.store.publish_manifest(draft)
        attempts = snapshot.attempts
        event = JobAttemptRecord(
            attempt=1,
            status=draft.status,
            current_stage=draft.current_stage,
            recorded_at=draft.completed_at or datetime.now(UTC),
            job_manifest_uri=reference.artifact_uri,
            job_manifest_checksum=reference.artifact_checksum,
        )
        private.persistence.save_job(draft, reference, event, owner_user_id=actor.user_id)
        with private.persistence.database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_scene_heads(job_id,generation,allocation_sequence,head_checksum,payload) VALUES (?,?,?,?,?)",
                (job_id, head.generation, head.allocation_sequence, head.head_checksum, head.model_dump_json()),
            )
            if attempts:
                tx.execute("DELETE FROM r2s_job_events WHERE job_id=?", (job_id,))
                for version, attempt in enumerate(attempts, 1):
                    tx.execute(
                        "INSERT INTO r2s_job_events(job_id,version,payload) VALUES (?,?,?)",
                        (job_id, version, attempt.model_dump_json()),
                    )
                tx.execute("UPDATE r2s_jobs SET version=? WHERE job_id=?", (len(attempts), job_id))
            for run in snapshot.validation_runs:
                tx.execute(
                    "INSERT INTO r2s_validation_runs(run_id,job_id,candidate_checksum,config_checksum,attempt,status,run_checksum,payload) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        run.run_id,
                        run.job_id,
                        run.candidate_checksum,
                        run.validation_config_checksum,
                        run.attempt,
                        run.status.value,
                        run.run_checksum,
                        run.model_dump_json(),
                    ),
                )
            for selection in snapshot.validation_selections:
                tx.execute(
                    "INSERT INTO r2s_validation_selections(job_id,candidate_checksum,config_checksum,run_id,report_checksum,generation,selection_checksum,payload) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        selection.job_id,
                        selection.candidate_checksum,
                        selection.validation_config_checksum,
                        selection.run_id,
                        selection.report_checksum,
                        selection.generation,
                        selection.selection_checksum,
                        selection.model_dump_json(),
                    ),
                )
        session = DemoSession(
            session_id=session_id,
            sample_id=sample_id,
            job_id=job_id,
            project_id=job.project_id,
            source_revision=head.scene_revision,
            actor_id=actor.user_id,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.product_demo_session_seconds),
            protected_uris=snapshot.protected_uris,
        )
        temporary = root / "session.json.tmp"
        temporary.write_text(session.model_dump_json())
        temporary.replace(root / "session.json")
        (root / "heartbeat").touch()
        (root / "initializing.json").unlink()
        return session
    except BaseException:
        shutil.rmtree(root)
        raise
    finally:
        ownership.close()


def create_session(settings: Settings, registry: ProjectRegistry, sample_id: str) -> DemoSession:
    base = session_root(settings)
    base.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (base / "creation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        purge_sessions(settings)
        if (
            sum(1 for path in base.iterdir() if _TOKEN.fullmatch(path.name) and path.is_dir())
            >= settings.product_demo_max_sessions
        ):
            raise DemoUnavailableError("Các phiên demo đang đầy; thử lại sau khi có người thoát")
        return _create_session(settings, registry, sample_id)


def get_session(settings: Settings, session_id: str) -> DemoSession:
    root = session_path(settings, session_id)
    try:
        session = DemoSession.model_validate_json((root / "session.json").read_bytes())
        if (
            session.session_id != session_id
            or (root / "closed").exists()
            or (root / "initializing.json").exists()
            or session.expires_at <= datetime.now(UTC)
            or datetime.now(UTC).timestamp() - (root / "heartbeat").stat().st_mtime > settings.product_demo_idle_seconds
        ):
            raise DemoSessionUnavailableError("Phiên demo đã kết thúc; mở lại mẫu để tạo phiên mới")
        DemoLibrary(settings.product_demo_dir).bundle(session.sample_id).manifest()
        return session
    except (OSError, ValueError, DemoUnavailableError) as error:
        raise DemoSessionUnavailableError("Phiên demo đã kết thúc hoặc không còn khả dụng") from error


def touch_session(settings: Settings, session_id: str) -> None:
    get_session(settings, session_id)
    try:
        (session_path(settings, session_id) / "heartbeat").touch()
    except FileNotFoundError as error:
        raise DemoSessionUnavailableError("Phiên demo đã kết thúc") from error


def load_runtime(settings: Settings, source: ProjectRegistry, session: DemoSession) -> DemoRuntime:
    private_settings = session_settings(settings, session.session_id)
    key = str(private_settings.artifact_root)
    with _runtime_lock:
        cached = _runtimes.get(key)
        if cached is not None:
            _runtimes.move_to_end(key)
            return cached
    registry = _registry(private_settings, source)
    assert registry.persistence is not None
    actor = AuthService(registry.persistence.database).get_user(session.actor_id)
    if actor is None:
        raise DemoSessionUnavailableError("Không đọc được quyền của phiên demo")
    runtime = DemoRuntime(private_settings, registry, actor)
    with _runtime_lock:
        _runtimes[key] = runtime
        _runtimes.move_to_end(key)
        while len(_runtimes) > 32:
            _runtimes.popitem(last=False)
    return runtime


@contextmanager
def hold_session(settings: Settings, session_id: str, *, exclusive: bool = False) -> Iterator[None]:
    """Cross-process ownership: cleanup never removes files still used by an API or worker."""
    root = session_path(settings, session_id)
    with (root / "session.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            get_session(settings, session_id)
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def close_session(settings: Settings, session_id: str) -> None:
    root = session_path(settings, session_id)
    try:
        if root.is_dir():
            (root / "closed").touch()
    except FileNotFoundError:
        pass  # Concurrent cleanup already removed this session.
    with _runtime_lock:
        _runtimes.pop(str(root / "artifacts"), None)


def purge_sessions(settings: Settings) -> int:
    """Remove only expired/closed session directories with no API/worker owner."""
    base = session_root(settings)
    if not base.is_dir():
        return 0
    removed = 0
    for root in base.iterdir():
        if not _TOKEN.fullmatch(root.name) or root.is_symlink() or not root.is_dir():
            continue
        try:
            try:
                metadata = DemoSession.model_validate_json((root / "session.json").read_bytes())
                if metadata.session_id != root.name:
                    continue
                if (
                    not (root / "closed").exists()
                    and metadata.expires_at > datetime.now(UTC)
                    and (root / "heartbeat").exists()
                    and datetime.now(UTC).timestamp() - (root / "heartbeat").stat().st_mtime
                    <= settings.product_demo_idle_seconds
                ):
                    continue
            except FileNotFoundError:
                creating = _SessionCreation.model_validate_json((root / "initializing.json").read_bytes())
                if creating.session_id != root.name or creating.created_at + timedelta(
                    seconds=settings.product_demo_session_seconds
                ) > datetime.now(UTC):
                    continue
            with (root / "session.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                shutil.rmtree(root)
                with _runtime_lock:
                    _runtimes.pop(str(root / "artifacts"), None)
                removed += 1
        except (FileNotFoundError, ValueError):
            continue
    return removed
