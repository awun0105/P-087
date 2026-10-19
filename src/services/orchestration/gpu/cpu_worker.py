"""Opt-in CPU lane; resource/dependency preflight precedes any claim."""

import argparse
import os
import resource
import shutil
import time

from src.config import get_settings
from src.services.orchestration.gpu.config import GpuSettings
from src.services.orchestration.gpu.state import supports
from src.services.orchestration.jobs.admission import ResourceAdmission
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.registration_worker import RegistrationOperationWorker
from src.services.orchestration.processing.capability import _live_ram_gb
from src.services.orchestration.projects.registry import get_project_registry
from src.services.orchestration.samples.session_worker import process_demo_session
from src.services.orchestration.scene.objectify_queue import process_next as scene_next
from src.services.orchestration.storage import runtime_resolver
from src.services.orchestration.uploads.scene_imports import ImportService


def preflight(policy: GpuSettings) -> None:
    import numpy  # noqa: F401
    import scipy  # noqa: F401

    available = _live_ram_gb()
    if available is None or available < policy.cpu_lane_ram_gb + 1:
        raise RuntimeError("CPU lane requires its configured RAM budget plus 1 GiB API headroom")
    if shutil.which("node") is None:
        raise RuntimeError("CPU import lane requires the packaged Node runtime")
    # Isolate task virtual memory/CPU from the API process. Admission still checks task-specific resources.
    limit = int(policy.cpu_lane_ram_gb * 1024**3)
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    if hasattr(os, "sched_getaffinity"):
        cpus = sorted(os.sched_getaffinity(0))
        os.sched_setaffinity(0, {cpus[-1]})
    os.environ.update({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "GPU_CPU_LANE": "true"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--demo-operation", choices=["registration", "scene"])
    parser.add_argument("--demo-parent-pid", type=int)
    args = parser.parse_args()
    if args.demo_parent_pid is not None:
        import ctypes

        if os.getppid() != args.demo_parent_pid or ctypes.CDLL(None).prctl(1, 15) != 0:
            return 130
    policy = GpuSettings()
    if not policy.cpu_lane_enabled:
        return 0
    preflight(policy)
    settings, registry = get_settings(), get_project_registry()
    gate = ResourceAdmission(registry, settings)
    registration = RegistrationOperationWorker(registry, settings, gate)
    imports = ImportService(
        RuntimeDatabase(settings.database_url),
        runtime_resolver(settings),
        settings.product_worker_root / "imports",
        max_uncompressed_bytes=settings.product_upload_max_bytes * 2,
    )
    while True:
        handled = (
            registration.process_next()
            or (supports("scene") and scene_next(registry, settings))
            or imports.process_next(admission=gate)
            or process_demo_session(settings, registry, gate)
        )
        if args.once:
            return 0
        if not handled:
            time.sleep(settings.product_queue_poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
