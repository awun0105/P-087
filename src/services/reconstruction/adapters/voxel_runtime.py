"""Process REC-05: pin CLI, lưu evidence và dừng cả process group khi timeout."""

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from threading import Event
from typing import TextIO

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.runtime_env import RuntimeSettings
from src.services.process_control import ProgressWatchdog, file_size_marker


class VoxelRuntimeSettings(RuntimeSettings):
    """Runtime được deployment inject; không cài npm hoặc đổi driver ngầm."""

    cli: Path
    module_path: Path
    node_command: tuple[str, ...] = ("node",)
    timeout_seconds: float = Field(default=300, gt=0, allow_inf_nan=False)
    #: Log không tăng trong khoảng này thì coi như treo. Log voxel thật chỉ có pha dưới 0,2 s (xem report T-043),
    #: nên 120 s là hệ số lớn; `timeout_seconds` vẫn là lưới cuối.
    stall_seconds: float = Field(default=120, gt=0, allow_inf_nan=False)
    environment: dict[str, str] = Field(default_factory=dict)
    model_config = SettingsConfigDict(env_prefix="R2S_VOXEL_", extra="forbid")


class GeometryError(ValueError):
    """Lỗi actionable của geometry boundary; nguyên nhân giữ bằng exception cause."""


class GeometryCancelledError(GeometryError):
    """Geometry child was killed and reaped after its durable operation was cancelled."""


class VoxelProcess:
    """Logs thuộc private attempt; chưa publish canonical geometry khi chưa đủ gate."""

    def __init__(self, settings: VoxelRuntimeSettings) -> None:
        self.settings = settings
        if not settings.node_command or any(not value for value in settings.node_command):
            raise ValueError("empty Node runtime command")

    def run(
        self,
        arguments: tuple[str, ...],
        target: tuple[Path, str],
        *,
        cancel_event: Event | None = None,
    ) -> str:
        """Không shell interpolation; mỗi invocation có log riêng không overwrite."""
        workspace, name = target
        log_path = workspace / f"{name}.log"
        start = time.monotonic()
        with log_path.open("x") as log:
            log.write(json.dumps({"tool": name}) + "\n")
            log.flush()
            code = self._invoke(arguments, (workspace, log), cancel_event=cancel_event)
            log.write(json.dumps({"returncode": code, "elapsed_seconds": time.monotonic() - start}) + "\n")
        if code:
            raise GeometryError(f"Geometry tool {name} failed (exit {code}); inspect attempt log")
        return log_path.read_text()

    def _invoke(
        self,
        arguments: tuple[str, ...],
        target: tuple[Path, TextIO],
        *,
        cancel_event: Event | None = None,
    ) -> int:
        workspace, log = target
        try:
            with subprocess.Popen(
                [*self.settings.node_command, *arguments],
                cwd=workspace,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=os.environ | self.settings.environment,
            ) as process:
                deadline = time.monotonic() + self.settings.timeout_seconds
                watchdog = ProgressWatchdog(self.settings.stall_seconds, [file_size_marker(Path(log.name))])
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        self._kill(process)
                        process.wait()
                        log.write("\nGEOMETRY_CANCELLED\n")
                        raise GeometryCancelledError("Geometry operation was cancelled")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._kill(process)
                        process.wait()
                        log.write("\nGEOMETRY_TIMEOUT\n")
                        raise GeometryError("Geometry timeout; inspect attempt log and configured limits")
                    watchdog.poll()
                    if watchdog.stalled():
                        self._kill(process)
                        process.wait()
                        log.write("\nGEOMETRY_STALLED\n")
                        raise GeometryError(
                            f"Geometry không tiến triển trong {int(self.settings.stall_seconds)} giây và đã bị dừng. "
                            "Xem log của lượt chạy; nếu scene rất lớn, tăng R2S_VOXEL_STALL_SECONDS."
                        )
                    try:
                        return process.wait(timeout=min(0.1, remaining))
                    except subprocess.TimeoutExpired:
                        continue
        except OSError as error:
            raise GeometryError("Geometry runtime unavailable; check configured Node and CLI") from error

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        try:
            if hasattr(os, "killpg"):
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass

    def cli(
        self,
        arguments: tuple[str, ...],
        target: tuple[Path, str],
        *,
        cancel_event: Event | None = None,
    ) -> str:
        """CLI path resolve trước đổi cwd."""
        command = (str(self.settings.cli.resolve()), *arguments)
        if cancel_event is None:
            return self.run(command, target)
        return self.run(command, target, cancel_event=cancel_event)

    def qualify(self, workspace: Path, *, cancel_event: Event | None = None) -> str:
        """Version/revision và flags được xác minh từ executable thực tế."""
        version = "splat-transform v3.6.6 (afbc281)"
        output = self.cli(("--version",), (workspace, "version"), cancel_event=cancel_event)
        if version not in output.splitlines():
            raise GeometryError("Geometry runtime differs from qualified splat-transform 3.6.6 afbc281")
        help_text = self.cli(("--help",), (workspace, "help"), cancel_event=cancel_event)
        required = (
            "--filter-cluster",
            "--voxel-size",
            "--voxel-opacity",
            "--voxel-carve",
            "--seed-pos",
            "--collision-mesh",
        )
        if any(flag not in help_text for flag in required):
            raise GeometryError("Geometry CLI lacks required voxel/carve controls")
        if cancel_event is None:
            self.run(("--version",), (workspace, "node"))
            self.cli(("--list-gpus",), (workspace, "gpus"))
        else:
            self.run(("--version",), (workspace, "node"), cancel_event=cancel_event)
            self.cli(("--list-gpus",), (workspace, "gpus"), cancel_event=cancel_event)
        return version


def require_carve(log: str) -> None:
    """Upstream exit 0 có thể bỏ carve; không coi đó là successful geometry."""
    rejected = ("skipping carve", "skipping nav carving", "no navigable cells remain")
    if any(message in log.lower() for message in rejected):
        raise GeometryError("Capsule carve was skipped; correct navigation seed or capsule config")


def require_external_fill(log: str) -> None:
    """Exit zero can return the original grid when the seed is not enclosed."""
    text = log.lower()
    if "fill exterior" not in text or "skipping exterior fill" in text or "no navigable cells remain" in text:
        raise GeometryError("External fill was not applied; inspect seed, crop and room enclosure")
