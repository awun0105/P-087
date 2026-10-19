"""Dispatch private demo queues through a reservation in the shared machine ledger."""

import fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from src.config import Settings
from src.services.orchestration.gpu.classification import scene_gpu
from src.services.orchestration.gpu.state import cpu_lane, supports
from src.services.orchestration.jobs.admission import (
    OperationAdmissionRequest,
    OperationResourceProfile,
    ResourceAdmission,
)
from src.services.orchestration.jobs.queue import waiting_jobs
from src.services.orchestration.processing.procfs import process_table, process_tree
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.samples import distributed
from src.services.orchestration.samples.session_context import DemoRuntime
from src.services.orchestration.samples.sessions import (
    DemoSessionUnavailableError,
    get_session,
    hold_session,
    load_runtime,
    purge_sessions,
    session_path,
    session_root,
    session_settings,
)

logger = logging.getLogger(__name__)
_cursor = ""


DemoOperation = Literal["pipeline", "registration", "validation", "scene"]


def _pending(registry: ProjectRegistry) -> DemoOperation | None:
    assert registry.persistence is not None
    if supports("pipeline") and waiting_jobs(registry):
        return "pipeline"
    with registry.persistence.database.transaction() as tx:
        for kind, sql in (
            (
                "registration",
                "SELECT payload FROM r2s_registration_operations WHERE state IN ('QUEUED','WAITING_RESOURCES','RUNNING')",
            ),
            (
                "validation",
                "SELECT payload FROM r2s_validation_operations WHERE status IN ('QUEUED','WAITING_RESOURCES','CLAIMED','RUNNING','CANCEL_REQUESTED')",
            ),
            ("scene", "SELECT payload FROM r2s_scene_requests WHERE status IN ('queued','running')"),
        ):
            if not supports(kind):
                continue
            for row in tx.execute(sql).fetchall():
                value = json.loads(row[0])
                if cpu_lane() and kind == "scene":
                    from src.config import get_settings
                    from src.services.orchestration.scene.extraction import box_candidates_require_gpu

                    if scene_gpu(value.get("mode", "objectify"), box_candidates_require_gpu(get_settings())):
                        continue
                state = value.get("status", value.get("state", ""))
                if state in {"QUEUED", "WAITING_RESOURCES", "queued"}:
                    return kind
                expires = value.get("lease_expires_at")
                if expires and datetime.fromisoformat(expires) <= datetime.now(UTC):
                    return kind
    return None


def _profile(runtime: DemoRuntime, job_id: str, kind: DemoOperation) -> OperationResourceProfile:
    gate = ResourceAdmission(runtime.registry, runtime.settings)
    baseline = gate.operation_profile_for_job(runtime.registry.get_job(job_id), gpu_required=not cpu_lane())
    if kind == "validation":
        from src.services.orchestration.review.validation_worker import IsaacValidationWorker

        worker = IsaacValidationWorker(runtime.registry, runtime.settings, gate)
        return worker.resource_profile or baseline
    if kind == "registration":
        from src.services.orchestration.jobs.registration_operations import RegistrationOperationRecord
        from src.services.orchestration.jobs.registration_worker import RegistrationOperationWorker

        assert runtime.registry.persistence is not None
        with runtime.registry.persistence.database.transaction() as tx:
            row = tx.execute(
                "SELECT payload FROM r2s_registration_operations WHERE state IN ('QUEUED','WAITING_RESOURCES','RUNNING') ORDER BY created_at,operation_id LIMIT 1"
            ).fetchone()
        if row is None:
            return baseline
        operation = RegistrationOperationRecord.model_validate_json(row[0])
        registration = RegistrationOperationWorker(runtime.registry, runtime.settings, gate)
        root = runtime.settings.product_worker_root / "demo-admission"
        root.mkdir(parents=True, exist_ok=True)
        # Reuse the native source verification and resource calculation before reserving
        # shared RAM/disk; the child validates the same checksummed inputs again.
        with tempfile.TemporaryDirectory(dir=root) as name:
            source = registration.source_resolver.resolve(operation.request, Path(name))
            target = runtime.registry.runtime_resolver.require(operation.request.target_rgb_geometry_ref)
            return registration._resource_profile(operation, source, source.path.stat().st_size, target.stat().st_size)
    return baseline


def _run(settings: Settings, session_id: str, kind: DemoOperation) -> None:
    root = session_path(settings, session_id)
    root.mkdir(parents=True, exist_ok=True)
    private = session_settings(settings, session_id)
    environment = dict(os.environ)
    environment.update(
        {
            "DATABASE_URL": private.database_url,
            "ARTIFACT_ROOT": str(root / "artifacts"),
            "PRODUCT_WORKER_ROOT": str(root / "workers"),
            "PRODUCT_RERUN_RECORDING_DIR": str(root / "recordings"),
            "PRODUCT_DEMO_DIR": str(root / "library"),
            "PRODUCT_TRASH_ROOT": str(root / "trash"),
            "AUTH_REQUIRED": str(private.auth_required).lower(),
            "ARTIFACT_S3_BUCKET": private.artifact_s3_bucket or "",
            "ARTIFACT_S3_PREFIX": private.artifact_s3_prefix,
            "PRODUCT_DEMO_BASELINE_PREFIX": private.product_demo_baseline_prefix or "",
            "PRODUCT_FIXTURE_MODE": "false",
            "PRODUCT_DEMO_SESSION_WORKER": "true",
        }
    )
    owned: dict[int, float] = {}
    with (root / "worker.log").open("ab") as log:
        module = (
            "src.services.orchestration.gpu.cpu_worker" if cpu_lane() else "src.services.orchestration.jobs.worker_cli"
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                module,
                "--once",
                "--demo-operation",
                kind,
                "--demo-parent-pid",
                str(os.getpid()),
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            while process.poll() is None:
                table = process_table()
                if table is not None:
                    anchors = {pid for pid, started in owned.items() if pid in table and table[pid].started == started}
                    owned.update({pid: table[pid].started for pid in process_tree(table, {process.pid} | anchors)})
                try:
                    get_session(settings, session_id)
                except DemoSessionUnavailableError:
                    break
                time.sleep(1 if distributed.enabled(settings) else 0.25)
        finally:
            if process.poll() is None:
                process.terminate()  # Worker handles SIGTERM and cleans its GPU/tool children.
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    table = process_table()
                    if table is not None:
                        for pid, started in owned.items():
                            if pid in table and table[pid].started == started:
                                try:
                                    os.kill(pid, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                    process.kill()
                    process.wait()


def process_demo_session(settings: Settings, source: ProjectRegistry, admission: ResourceAdmission) -> bool:
    """At most one session operation; normal jobs keep priority in the caller."""
    global _cursor
    if settings.product_demo_session_worker:
        return False
    purge_sessions(settings)
    if distributed.enabled(settings):
        ids = distributed.list_sessions(settings)
        ids = [value for value in ids if value > _cursor] + [value for value in ids if value <= _cursor]
        for session_id in ids:
            try:
                with distributed.hold(settings, session_id, worker=True) as claimed:
                    if claimed and _dispatch(settings, source, admission, session_id):
                        _cursor = session_id
                        return True
            except DemoSessionUnavailableError:
                continue
        return False
    base = session_root(settings)
    if not base.is_dir():
        return False
    roots = sorted(path for path in base.iterdir() if path.is_dir() and not path.is_symlink())
    roots = [path for path in roots if path.name > _cursor] + [path for path in roots if path.name <= _cursor]
    for root in roots:
        try:
            session = get_session(settings, root.name)
            with (root / "worker.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                with hold_session(settings, session.session_id):
                    if _dispatch(settings, source, admission, session.session_id):
                        _cursor = root.name
                        return True
        except (DemoSessionUnavailableError, FileNotFoundError):
            continue
        except (OSError, ValueError) as error:
            logger.warning("Demo dispatch failed: %s", type(error).__name__)
    return False


def _dispatch(settings: Settings, source: ProjectRegistry, admission: ResourceAdmission, session_id: str) -> bool:
    session = get_session(settings, session_id)
    runtime = load_runtime(settings, source, session)
    kind = _pending(runtime.registry)
    if kind is None:
        return False
    job = runtime.registry.get_job(session.job_id)
    profile = _profile(runtime, session.job_id, kind).model_copy(update={"measured": False})
    request = OperationAdmissionRequest(
        operation_kind="demo_session",
        operation_id=f"demo-{session.session_id}",
        parent_kind="job",
        parent_id=session.job_id,
        input_checksum=job.job_manifest_checksum,
        config_checksum=job.config_checksum,
        resources=profile,
    )
    result = admission.admit_operation(request)
    root = session_path(settings, session_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / "resource-wait.json").write_text(json.dumps(result.model_dump(mode="json", exclude={"request"})))
    if result.status != "admitted":
        return False
    try:
        _run(settings, session_id, kind)
    finally:
        admission.release_operation(request)
    return True
