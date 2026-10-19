"""Inventory demand and live execution across main and registered demo schemas."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.config import Settings
from src.services.orchestration.gpu.catalog import ReleaseCatalog
from src.services.orchestration.gpu.classification import import_gpu, scene_gpu
from src.services.orchestration.jobs.admission import STALE_AFTER
from src.services.orchestration.jobs.database import RuntimeDatabase, demo_database_url
from src.services.orchestration.jobs.queue import waiting_jobs
from src.services.orchestration.projects.registry import ProjectRegistry


@dataclass(frozen=True)
class Demand:
    scope: str
    kind: str
    operation: str
    profiles: tuple[str, ...]


@dataclass
class Workload:
    pending: list[Demand] = field(default_factory=list)
    active: int = 0
    cpu_pending: int = 0
    blocked: list[str] = field(default_factory=list)
    complete: bool = True


def _live(value: object, now: datetime) -> bool:
    return bool(value) and datetime.fromisoformat(str(value)) > now


def scan_scope(
    database: RuntimeDatabase,
    registry: ProjectRegistry,
    catalog: ReleaseCatalog,
    *,
    accept_demand: bool = True,
    boxes_gpu: bool = True,
    now: datetime | None = None,
) -> Workload:
    now = now or datetime.now(UTC)
    result = Workload()
    scope = database.scope or "main"

    def pending(
        kind: str,
        operation: str,
        runtime: str | None = None,
        gpu: bool = True,
        seed: int | None = None,
        required: dict | None = None,
    ) -> None:
        if not accept_demand:
            return
        if not gpu:
            result.cpu_pending += 1
            return
        required = required or {}
        profiles = tuple(
            p.name
            for p in catalog.compatible(kind, runtime)
            if (kind != "pipeline" or p.execution.seed == seed)
            and p.min_vram_gb >= (required.get("vram") or 0)
            and p.min_ram_gb >= (required.get("ram") or 0)
            and p.scratch_gb >= (required.get("disk") or 0)
        )
        if profiles:
            result.pending.append(Demand(scope, kind, operation, profiles))
        else:
            result.blocked.append(f"{scope}:{kind}:unsupported_runtime_or_resources")

    # Semantic job queue includes reviewed-preview and finalize, not all RUNNING jobs.
    for item in waiting_jobs(registry):
        job = registry.get_job(item.job_id)
        runtime = job.runtime_manifest_checksum if job.stage_artifacts else None
        with database.transaction() as tx:
            wait = tx.execute("SELECT payload FROM r2s_resource_waits WHERE job_id=?", (item.job_id,)).fetchone()
        required = {}
        if wait:
            payload = json.loads(wait[0])
            if payload.get("job_manifest_checksum") == getattr(job, "job_manifest_checksum", None):
                required = payload.get("required_gb") or {}
        pending("pipeline", item.job_id, runtime, seed=getattr(job, "seed", None), required=required)
    with database.transaction() as tx:
        for (expires,) in tx.execute("SELECT lease_expires_at FROM r2s_job_leases").fetchall():
            result.active += int(_live(expires, now))
        for table, state_key, queued, running, kind in (
            ("r2s_scene_requests", "status", {"queued"}, {"running"}, "scene"),
            ("r2s_registration_operations", "state", {"QUEUED", "WAITING_RESOURCES"}, {"RUNNING"}, "registration"),
            (
                "r2s_validation_operations",
                "status",
                {"QUEUED", "WAITING_RESOURCES"},
                {"CLAIMED", "RUNNING", "CANCEL_REQUESTED"},
                "validation",
            ),
            ("r2s_import_operations", "status", {"QUEUED", "WAITING"}, {"RUNNING"}, "import"),
        ):
            for (raw,) in tx.execute(f"SELECT payload FROM {table}").fetchall():
                value = json.loads(raw)
                state = value[state_key]
                if state in running:
                    # Unknown/missing lease on a RUNNING row is unsafe, not proof of idleness.
                    if not value.get("lease_expires_at"):
                        result.complete = False
                    result.active += int(_live(value.get("lease_expires_at"), now))
                if state not in queued and not (
                    state in running and value.get("lease_expires_at") and not _live(value["lease_expires_at"], now)
                ):
                    continue
                gpu = True
                if kind == "registration":
                    gpu = False
                elif kind == "scene":
                    gpu = scene_gpu(value.get("mode", "objectify"), boxes_gpu)
                elif kind == "import":
                    row = tx.execute(
                        "SELECT payload FROM r2s_imports WHERE import_id=?", (value["import_id"],)
                    ).fetchone()
                    if row is None:
                        result.complete = False
                        continue
                    gpu = import_gpu(json.loads(row[0])["input_kind"], value.get("gpu_index"))
                required = (value.get("resource_wait") or {}).get("required_gb", {})
                pending(kind, value.get("operation_id", value.get("run_id", "scene")), gpu=gpu, required=required)
        for (raw,) in tx.execute("SELECT payload FROM r2s_resource_reservations").fetchall():
            value = json.loads(raw)
            heartbeat = value.get("heartbeat_at")
            if not heartbeat or (now - datetime.fromisoformat(heartbeat)).total_seconds() < STALE_AFTER.total_seconds():
                result.active += 1
    return result


def inventory(settings: Settings, source: ProjectRegistry, catalog: ReleaseCatalog) -> Workload:
    from src.services.orchestration.jobs.worker_cli import recover_expired_leases
    from src.services.orchestration.samples import distributed
    from src.services.orchestration.samples.sessions import _registry, session_settings

    # Existing recovery uses CAS + lease expiry; never resets a healthy attempt.
    recover_expired_leases(source)
    assert source.persistence is not None
    result = scan_scope(
        source.persistence.database,
        source,
        catalog,
        boxes_gpu=any(p.scene_boxes_require_gpu for p in catalog.profiles if "scene" in p.kinds),
    )
    if not distributed.enabled(settings):
        return result
    with source.persistence.database.transaction() as tx:
        sessions = tx.execute(
            "SELECT session_id,state,payload FROM r2s_demo_sessions WHERE state IN ('open','closed')"
        ).fetchall()
    for session_id, state, raw in sessions:
        try:
            # Avoid load_runtime(): scanner must not copy recordings or resolve native geometry.
            payload = json.loads(raw)
            private = session_settings(settings, session_id, payload["sample_id"])
            db = RuntimeDatabase(demo_database_url(settings.database_url, session_id))
            scoped = _registry(private, source)
            recover_expired_leases(scoped)
            work = scan_scope(
                db,
                scoped,
                catalog,
                accept_demand=state == "open",
                boxes_gpu=any(p.scene_boxes_require_gpu for p in catalog.profiles if "scene" in p.kinds),
            )
            result.pending.extend(work.pending)
            result.active += work.active
            result.cpu_pending += work.cpu_pending
            result.blocked.extend(work.blocked)
            result.complete &= work.complete
        except (KeyError, ValueError, OSError, RuntimeError):
            # Cleanup races and inaccessible scopes require a fresh complete pass before termination.
            result.complete = False
    return result
