"""Managed worker registration and whole-dispatch publication protection."""

import logging
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from src.config import Settings
from src.services.orchestration.artifacts.checksum import sha256_file
from src.services.orchestration.gpu.catalog import ReleaseProfile
from src.services.orchestration.gpu.state import StateStore
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.processing.capability import _live_ram_gb, bound_gpu

logger = logging.getLogger(__name__)


class ManagedWorker:
    def __init__(self, settings: Settings, profile: ExecutionProfile) -> None:
        self.token = os.environ.get("GPU_BOOT_TOKEN", "")
        self.key = f"{os.getpid()}-{uuid4().hex}"
        self.store: StateStore | None = None
        self.stop = Event()
        self.thread: Thread | None = None
        if not self.token:
            return
        expected = ReleaseProfile.model_validate_json(os.environ["GPU_EXPECTED_PROFILE"])
        if (
            not expected.execution.accepts_runtime(profile.job_runtime_checksum)
            or expected.execution.config_checksum != profile.config_checksum
            or expected.execution.seed != profile.seed
        ):
            raise ValueError("Managed worker runtime does not match pinned release")
        gpu, ram = bound_gpu(), _live_ram_gb()
        settings.product_worker_root.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(settings.product_worker_root).free / 1024**3
        if (
            gpu is None
            or gpu.total_gb < expected.min_vram_gb
            or ram is None
            or ram < expected.min_ram_gb
            or disk < expected.scratch_gb
        ):
            raise ValueError("Managed worker allocation does not meet qualified release requirements")
        parsed = urlsplit(settings.database_url)
        main_url = (
            urlunsplit(parsed._replace(fragment=""))
            if parsed.scheme in {"postgres", "postgresql"}
            else settings.database_url
        )
        self.store = StateStore(RuntimeDatabase(main_url), os.environ["GPU_DEPLOYMENT_ID"])
        # Prove R2 read access before advertising ready. Writes remain verified by existing publishers.
        from src.services.orchestration.storage import artifact_remote

        remote = artifact_remote(settings)
        if remote is None:
            raise ValueError("Managed worker requires remote artifacts")
        probe_key = remote.key(f"_control/probes/{os.environ['GPU_INTENT_ID']}/{self.key}")
        with tempfile.TemporaryDirectory(dir=settings.product_worker_root) as temporary:
            path = Path(temporary) / "probe"
            path.write_bytes(b"real2sim-worker-probe")
            checksum = sha256_file(path)
            try:
                remote.store.put_file(probe_key, path, checksum)
                head = remote.store.head(probe_key)
                if head is None or head.checksum != checksum:
                    raise RuntimeError("Worker R2 publication preflight failed")
                fetched = Path(temporary) / "fetched"
                remote.store.get_file(probe_key, fetched)
                if sha256_file(fetched) != checksum:
                    raise RuntimeError("Worker R2 read preflight failed")
            finally:
                remote.store.delete(probe_key)
        os.environ["GPU_WORKER_KEY"] = self.key
        self._touch(initial=True)
        self.thread = Thread(target=self._heartbeat, name="gpu-control-heartbeat", daemon=True)
        self.thread.start()

    def _touch(self, *, initial: bool = False) -> None:
        assert self.store is not None
        with self.store.locked() as (_, c, now):
            if c.boot_token != self.token or c.state in {"absent", "terminating"}:
                raise RuntimeError("Managed worker generation retired")
            current = c.workers.get(self.key, {"busy": False})
            c.workers[self.key] = {**current, "ready": True, "heartbeat": now}

    def _heartbeat(self) -> None:
        while not self.stop.wait(15):
            try:
                self._touch()
            except Exception as error:  # noqa: BLE001 - any failure must stop claims, never kill the thread silently
                logger.error("gpu_worker heartbeat stopped category=%s", type(error).__name__)
                self.stop.set()  # No further claims; existing execution remains fenced by queue leases.

    @contextmanager
    def operation(self) -> Iterator[bool]:
        if self.store is None:
            yield True
            return
        allowed = False
        with self.store.locked() as (_, c, now):
            allowed = (
                not self.stop.is_set()
                and c.boot_token == self.token
                and not c.drain
                and c.state in {"ready", "idle", "busy"}
            )
            if allowed:
                c.workers[self.key] = {"ready": True, "busy": False, "heartbeat": now}
        try:
            yield allowed
        finally:
            if allowed:
                with self.store.locked() as (_, c, now):
                    if c.boot_token == self.token:
                        c.workers[self.key] = {"ready": True, "busy": False, "heartbeat": now}

    def close(self) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        if self.store:
            with self.store.locked() as (_, c, _):
                c.workers.pop(self.key, None)
