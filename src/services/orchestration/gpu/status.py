"""Read-only view of the managed GPU for people waiting on a job: is a GPU on its way, and how long is left.

The controller owns `r2s_gpu_control` / `r2s_gpu_history`; this module only reads them (no row locks), so a
Studio page polling it never contends with the leader. The startup estimate is the median of real
provisioning + starting durations recorded for earlier pods of this deployment.
"""

import json
from datetime import UTC, datetime
from statistics import median
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.services.orchestration.gpu.state import Control, db_time
from src.services.orchestration.jobs.database import RuntimeDatabase

#: Used until the deployment has finished at least one cold start (image pull + worker preflight).
DEFAULT_STARTUP_SECONDS = 900
#: Controller states in which a pod has been requested but cannot take work yet.
_STARTING = frozenset({"provisioning", "starting"})
_READY = frozenset({"ready", "busy"})
_WINDING_DOWN = frozenset({"draining", "terminating"})
_COLD_START_PHASES = ("provisioning", "starting")

GpuCapacityState = Literal["unmanaged", "off", "starting", "ready", "draining", "blocked"]


class GpuCapacity(BaseModel):
    """What a waiting user needs: state, how long it has been, and a realistic remaining time."""

    model_config = ConfigDict(extra="forbid")

    state: GpuCapacityState
    since: datetime | None = None
    elapsed_seconds: int | None = None
    #: Typical cold start for this deployment; a job queued while the GPU is off waits about this long.
    expected_startup_seconds: int
    #: Only while starting; 0 once the estimate is exceeded (the UI then says "sắp xong").
    remaining_seconds: int | None = None
    #: Measured cold starts behind the estimate; 0 means the default is used.
    sample_count: int = 0


def expected_startup_seconds(history: list[dict]) -> tuple[int, int]:
    """Median cold start over earlier pods that actually reached ready; default when none did."""
    samples = []
    for record in history:
        phases = record.get("phase_seconds") or {}
        reached_ready = any(phases.get(state, 0) > 0 for state in _READY) or record.get("state") in _READY
        cold = sum(float(phases.get(state, 0) or 0) for state in _COLD_START_PHASES)
        if reached_ready and cold > 0:
            samples.append(cold)
    if not samples:
        return DEFAULT_STARTUP_SECONDS, 0
    return int(round(median(samples))), len(samples)


def gpu_capacity(database: RuntimeDatabase | None, deployment_id: str) -> GpuCapacity:
    """Current managed-GPU state; `unmanaged` when this API does not run the RunPod controller."""
    if database is None or not deployment_id or database.scope:
        return GpuCapacity(state="unmanaged", expected_startup_seconds=DEFAULT_STARTUP_SECONDS)
    with database.transaction() as tx:
        row = tx.execute("SELECT payload FROM r2s_gpu_control WHERE deployment_id=?", (deployment_id,)).fetchone()
        history = [
            json.loads(item[0])
            for item in tx.execute(
                "SELECT payload FROM r2s_gpu_history WHERE deployment_id=?", (deployment_id,)
            ).fetchall()
        ]
        now = db_time(tx)
    expected, samples = expected_startup_seconds(history)
    if row is None:
        return GpuCapacity(state="off", expected_startup_seconds=expected, sample_count=samples)
    raw = json.loads(row[0])
    control = Control(**{key: value for key, value in raw.items() if key in Control.__dataclass_fields__})

    def stamp(value: float) -> datetime | None:
        return datetime.fromtimestamp(value, UTC) if value else None

    common = {"expected_startup_seconds": expected, "sample_count": samples}
    if control.state in _STARTING:
        started = control.created_at or control.phase_since
        elapsed = max(0, int(now - started)) if started else None
        remaining = max(0, expected - elapsed) if elapsed is not None else expected
        return GpuCapacity(
            state="starting", since=stamp(started), elapsed_seconds=elapsed, remaining_seconds=remaining, **common
        )
    if control.state in _READY:
        return GpuCapacity(state="ready", since=stamp(control.phase_since), **common)
    if control.state in _WINDING_DOWN:
        return GpuCapacity(state="draining", since=stamp(control.phase_since), **common)
    if control.state == "unknown" or (control.state == "absent" and control.error and control.drain):
        return GpuCapacity(state="blocked", since=stamp(control.phase_since), **common)
    return GpuCapacity(state="off", **common)
