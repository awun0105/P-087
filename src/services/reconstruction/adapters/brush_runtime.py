"""Process boundary cho REC-04: version pin, timeout và logs của từng invocation."""

import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.models.contracts.manifests import ExecutionError, StageArtifact, StageId, StageStatus
from src.services.reconstruction.rgb.splat.visual import BrushConfig


class BrushRuntimeSettings(BaseSettings):
    """Executable paths ở composition root, không serialize vào published metadata."""

    command: tuple[str, ...] = ("brush",)
    expected_version: str = Field(min_length=1)
    runtime_identity: str = Field(min_length=1)
    timeout_seconds: float = Field(default=1800, gt=0, allow_inf_nan=False)
    environment: dict[str, str] = Field(default_factory=dict)
    model_config = SettingsConfigDict(env_prefix="REC04_BRUSH_", extra="forbid")


class VisualError(ValueError):
    """Worker nhận lỗi actionable; private process stderr chỉ nằm trong attempt log."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_failed_stage(self) -> StageArtifact:
        """Không biến partial PLY hoặc successful child exit thành stage success."""
        error = ExecutionError(
            error_code=self.code,
            stage_id=StageId.VISUAL_RECON,
            human_message=str(self),
            retryable=False,
            details={"action": "Inspect attempt logs and pinned runtime; retry in a fresh workspace"},
        )
        return StageArtifact(
            stage_id=StageId.VISUAL_RECON, status=StageStatus.FAILED, completed_at=datetime.now(UTC), error=error
        )


@dataclass(frozen=True)
class Invocation:
    """Tên log do adapter kiểm soát; argv không qua shell interpolation."""

    name: str
    command: tuple[str, ...]
    arguments: tuple[str, ...]


class VisualProcess:
    """Process group riêng để timeout không để lại trainer/child tiếp tục chạy."""

    def __init__(self, settings: BrushRuntimeSettings) -> None:
        if not settings.command or any(not arg for arg in settings.command):
            raise ValueError("empty Brush runtime command")
        self.settings = settings
        self.iteration_flag = "--total-train-iters"

    def run(self, invocation: Invocation, workspace: Path) -> str:
        """Log stdout/stderr trên disk; phiên bản/config probe cũng có evidence."""
        log_path = workspace / f"{invocation.name}.log"
        start = time.monotonic()
        with log_path.open("x") as log:
            arguments = [arg.replace(str(workspace.resolve()), "<workspace>") for arg in invocation.arguments]
            log.write(json.dumps({"tool": invocation.name, "arguments": arguments}) + "\n")
            log.flush()
            code = self._invoke(invocation, (workspace, log))
            log.write(json.dumps({"returncode": code, "elapsed_seconds": time.monotonic() - start}) + "\n")
        if code:
            raise VisualError("VISUAL_PROCESS_FAILED", f"{invocation.name} failed (exit {code})")
        return log_path.read_text()

    def _invoke(self, invocation: Invocation, target: tuple[Path, TextIO]) -> int:
        workspace, log = target
        try:
            with subprocess.Popen(
                [*invocation.command, *invocation.arguments],
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
                    self._kill_group(process)
                    log.write("\nVISUAL_TIMEOUT\n")
                    raise VisualError("VISUAL_TIMEOUT", "Visual tool exceeded configured timeout") from error
                except BaseException:
                    # Process boundary: SIGINT/SIGTERM được CLI chuyển thành interrupt.
                    # Brush/Node có session riêng; hủy Python cha không tự dừng chúng.
                    self._kill_group(process)
                    raise
        except OSError as error:
            raise VisualError("VISUAL_RUNTIME_UNAVAILABLE", "Cannot start configured visual runtime") from error

    @staticmethod
    def _kill_group(process: subprocess.Popen) -> None:
        """Kill/reap tool group, kể cả trainer con; race process vừa thoát là hợp lệ."""
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # Group đã thoát trước khi nhận tín hiệu; vẫn reap parent.
        process.wait()

    def qualify(self, workspace: Path) -> str:
        """Inspect đúng binary, không lấy version/CLI của checkout làm runtime truth."""
        command = self.settings.command
        text = self.run(Invocation("brush-version", command, ("--version",)), workspace)
        versions = [line.strip() for line in text.splitlines() if line.startswith(("brush ", "brush-cli "))]
        if len(versions) != 1 or versions[0].split()[-1] != self.settings.expected_version:
            raise VisualError("BRUSH_VERSION_MISMATCH", "Brush version differs from runtime pin")
        help_text = self.run(Invocation("brush-help", command, ("--help",)), workspace)
        self.iteration_flag = "--total-train-iters" if "--total-train-iters" in help_text else "--total-steps"
        required = (
            self.iteration_flag,
            "--max-resolution",
            "--sh-degree",
            "--seed",
            "--max-splats",
            "--refine-every",
            "--export-every",
            "--export-path",
            "--export-name",
        )
        if any(flag not in help_text for flag in required):
            raise VisualError("BRUSH_CLI_UNSUPPORTED", "Brush runtime lacks required training/export controls")
        return versions[0]


def brush_command(config: BrushConfig, workspace: Path, iteration_flag: str) -> tuple[str, ...]:
    """Không dùng eval split/resume/args.txt; dataset chỉ có registered train images."""
    values = config.model_dump(exclude={"schema_version", "sog_iterations"})
    args = [str((workspace / "training").resolve())]
    for key, value in values.items():
        flag = iteration_flag if key == "total_train_iters" else "--" + key.replace("_", "-")
        args.extend([flag, str(value)])
    args.extend(
        [
            "--export-every",
            str(config.total_train_iters),
            "--export-path",
            str((workspace / "output").resolve()),
            "--export-name",
            "visual.ply",
        ]
    )
    return tuple(args)
