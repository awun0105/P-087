"""Process REC-05: pin CLI, lưu evidence và dừng cả process group khi timeout."""

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import TextIO

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VoxelRuntimeSettings(BaseSettings):
    """Runtime được deployment inject; không cài npm hoặc đổi driver ngầm."""

    cli: Path
    module_path: Path
    node_command: tuple[str, ...] = ("node",)
    timeout_seconds: float = Field(default=300, gt=0, allow_inf_nan=False)
    environment: dict[str, str] = Field(default_factory=dict)
    model_config = SettingsConfigDict(env_prefix="REC05_VOXEL_", extra="forbid")


class GeometryError(ValueError):
    """Lỗi actionable của geometry boundary; nguyên nhân giữ bằng exception cause."""


class VoxelProcess:
    """Logs thuộc private attempt; chưa publish canonical geometry khi chưa đủ gate."""

    def __init__(self, settings: VoxelRuntimeSettings) -> None:
        self.settings = settings
        if not settings.node_command or any(not value for value in settings.node_command):
            raise ValueError("empty Node runtime command")

    def run(self, arguments: tuple[str, ...], target: tuple[Path, str]) -> str:
        """Không shell interpolation; mỗi invocation có log riêng không overwrite."""
        workspace, name = target
        log_path = workspace / f"{name}.log"
        start = time.monotonic()
        with log_path.open("x") as log:
            log.write(json.dumps({"tool": name}) + "\n")
            log.flush()
            code = self._invoke(arguments, (workspace, log))
            log.write(json.dumps({"returncode": code, "elapsed_seconds": time.monotonic() - start}) + "\n")
        if code:
            raise GeometryError(f"Geometry tool {name} failed (exit {code}); inspect attempt log")
        return log_path.read_text()

    def _invoke(self, arguments: tuple[str, ...], target: tuple[Path, TextIO]) -> int:
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
                try:
                    return process.wait(timeout=self.settings.timeout_seconds)
                except subprocess.TimeoutExpired as error:
                    if hasattr(os, "killpg"):
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait()
                    log.write("\nGEOMETRY_TIMEOUT\n")
                    raise GeometryError("Geometry timeout; inspect attempt log and configured limits") from error
        except OSError as error:
            raise GeometryError("Geometry runtime unavailable; check configured Node and CLI") from error

    def cli(self, arguments: tuple[str, ...], target: tuple[Path, str]) -> str:
        """CLI path resolve trước đổi cwd."""
        return self.run((str(self.settings.cli.resolve()), *arguments), target)

    def qualify(self, workspace: Path) -> str:
        """Version/revision và flags được xác minh từ executable thực tế."""
        version = "splat-transform v3.6.6 (afbc281)"
        output = self.cli(("--version",), (workspace, "version"))
        if version not in output.splitlines():
            raise GeometryError("Geometry runtime differs from qualified splat-transform 3.6.6 afbc281")
        help_text = self.cli(("--help",), (workspace, "help"))
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
        self.run(("--version",), (workspace, "node"))
        self.cli(("--list-gpus",), (workspace, "gpus"))
        return version


def require_carve(log: str) -> None:
    """Upstream exit 0 có thể bỏ carve; không coi đó là successful geometry."""
    rejected = ("skipping carve", "skipping nav carving", "no navigable cells remain")
    if any(message in log.lower() for message in rejected):
        raise GeometryError("Capsule carve was skipped; correct navigation seed or capsule config")
