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
from src.services.reconstruction.resume import CHECKPOINT_NAME
from src.services.reconstruction.rgb.splat.visual import BrushConfig


class BrushRuntimeSettings(BaseSettings):
    """Executable paths ở composition root, không serialize vào published metadata."""

    command: tuple[str, ...] = ("brush",)
    expected_version: str = Field(min_length=1)
    runtime_identity: str = Field(min_length=1)
    timeout_seconds: float = Field(default=1800, gt=0, allow_inf_nan=False)
    environment: dict[str, str] = Field(default_factory=dict)
    #: Khoảng cách mong muốn (số bước) giữa hai checkpoint khi có kho resume; 0 = không checkpoint.
    checkpoint_every: int = Field(default=2500, ge=0)
    #: Python của runtime có torch + gói `lpips` (thường là `data/scene_runtime`); None = không chấm LPIPS.
    lpips_python: Path | None = None
    hang_timeout_seconds: float = Field(default=180.0, ge=0)
    model_config = SettingsConfigDict(env_prefix="REC04_BRUSH_", extra="forbid")


FATAL_LOG_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("wgpu: requested wait timed out", "VISUAL_GPU_DEADLOCK", "GPU driver timeout/deadlock (wgpu wait timed out)"),
    ("VK_ERROR_DEVICE_LOST", "VISUAL_GPU_DEADLOCK", "Vulkan GPU device lost"),
    ("CUDA out of memory", "VISUAL_OUT_OF_MEMORY", "CUDA out of memory"),
    ("torch.cuda.OutOfMemoryError", "VISUAL_OUT_OF_MEMORY", "PyTorch CUDA out of memory"),
    ("DeviceLost", "VISUAL_GPU_DEADLOCK", "GPU device lost"),
    ("wgpu error: Validation Error", "VISUAL_GPU_DEADLOCK", "wgpu validation error"),
    ("Cannot allocate memory", "VISUAL_OUT_OF_MEMORY", "Cannot allocate memory (OOM)"),
)


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
            retryable=True,
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
        self.supports_eval_split = False

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
        log_path = workspace / f"{invocation.name}.log"
        poll_interval = 0.5
        hang_timeout = self.settings.hang_timeout_seconds
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
                deadline = time.monotonic() + self.settings.timeout_seconds
                last_log_offset = 0
                last_progress_time = time.monotonic()
                try:
                    while process.poll() is None:
                        now = time.monotonic()
                        if now >= deadline:
                            self._kill_group(process)
                            log.write("\nVISUAL_TIMEOUT\n")
                            raise VisualError("VISUAL_TIMEOUT", "Visual tool exceeded configured timeout")

                        if log_path.exists():
                            log_size = log_path.stat().st_size
                            if log_size > last_log_offset:
                                try:
                                    with log_path.open("r", encoding="utf-8", errors="replace") as reader:
                                        reader.seek(last_log_offset)
                                        new_text = reader.read()
                                        last_log_offset = reader.tell()
                                    last_progress_time = now
                                    for pattern, err_code, human_desc in FATAL_LOG_PATTERNS:
                                        if pattern in new_text:
                                            self._kill_group(process)
                                            log.write(f"\n{err_code}: {human_desc}\n")
                                            raise VisualError(err_code, f"{human_desc} detected in {invocation.name}")
                                except (OSError, UnicodeDecodeError):
                                    pass

                        if invocation.name == "brush-train" and hang_timeout > 0:
                            if now - last_progress_time > hang_timeout:
                                self._kill_group(process)
                                log.write("\nVISUAL_HANG_TIMEOUT\n")
                                raise VisualError(
                                    "VISUAL_HANG_TIMEOUT",
                                    f"{invocation.name} hung with no log progress for {int(hang_timeout)}s",
                                )

                        time.sleep(poll_interval)
                    return process.returncode
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
        self.supports_eval_split = all(flag in help_text for flag in EVAL_FLAGS)
        return versions[0]


#: Cờ Brush cho việc giữ lại ảnh không train và chấm ở bước cuối (ảnh render lưu cạnh file xuất).
EVAL_FLAGS = ("--eval-split-every", "--eval-every", "--eval-save-to-disk")


@dataclass(frozen=True)
class Checkpointing:
    """Xuất PLY định kỳ vào `directory`; `start_iter` > 0 = train tiếp từ `training/init.ply`."""

    directory: Path
    every: int
    start_iter: int = 0


def brush_command(
    config: BrushConfig, workspace: Path, iteration_flag: str, checkpointing: Checkpointing | None = None
) -> tuple[str, ...]:
    """Dataset chỉ có ảnh đã đăng ký pose; không dùng args.txt.

    `config.eval_split_every` = N: Brush giữ lại mỗi ảnh thứ N không train, chấm PSNR/SSIM một lần ở bước cuối và
    lưu ảnh render vào `<thư mục xuất>/eval_<bước>/` (để chấm LPIPS). Không đặt thì train trên mọi ảnh.

    Không checkpoint: xuất một lần ở bước cuối thành `output/visual.ply`. Có checkpoint: xuất
    `ckpt_<bước>.ply` định kỳ (bản ở bước cuối là kết quả), và train tiếp bằng `--start-iter` khi có.
    """
    values = config.model_dump(exclude={"schema_version", "sog_iterations"})
    args = [str((workspace / "training").resolve())]
    for key, value in values.items():
        flag = iteration_flag if key == "total_train_iters" else "--" + key.replace("_", "-")
        args.extend([flag, str(value)])
    if checkpointing is None:
        export = [str(config.total_train_iters), str((workspace / "output").resolve()), "visual.ply"]
    else:
        export = [str(checkpointing.every), str(checkpointing.directory.resolve()), CHECKPOINT_NAME]
        if checkpointing.start_iter:
            args.extend(["--start-iter", str(checkpointing.start_iter)])
    args.extend(["--export-every", export[0], "--export-path", export[1], "--export-name", export[2]])
    if config.eval_split_every is not None:
        args.extend(["--eval-every", str(config.total_train_iters), "--eval-save-to-disk"])
    return tuple(args)
