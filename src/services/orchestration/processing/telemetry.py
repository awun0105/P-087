"""Telemetry lấy mẫu theo cây tiến trình của một lần chạy công cụ, lưu nội bộ theo attempt.

Không sửa shared manifest/benchmark protocol. Peak là cực đại quan sát được qua
polling, không phải peak tuyệt đối. Cây tiến trình theo PPID nên gồm cả Brush và
splat-transform (chúng tự mở session riêng, không cùng process group với CLI cha).
VRAM có hai số tách bạch: theo PID do NVIDIA báo (None nếu driver không báo cho
tiến trình Vulkan/container) và mức đã dùng của cả GPU worker được ghim (gồm cả
tiến trình khác trên GPU đó).
"""

import math
import os
import stat
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.services.orchestration.processing.capability import (
    GpuReading,
    bound_gpu,
    measure_live_headroom,
    ram_available_gb,
)
from src.services.orchestration.processing.procfs import PROC_ROOT, process_table, process_tree, resident_gb

Outcome = Literal["completed", "failed", "cancelled", "timeout", "interrupted"]


class ResourceContext(BaseModel):
    """Bind mẫu đo với đúng CLI execution/config, không phải competing job state."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    job_id: str
    attempt_id: str
    tool: str
    config_checksum: str
    runtime_manifest_checksum: str
    #: Thông số số học của cấu hình job và model GPU: khoá để suy ngân sách cho job sau.
    params: dict[str, float] | None = None
    gpu_name: str | None = None
    #: Lúc bắt đầu có worker khác giữ chỗ trên cùng GPU không (None = không kiểm được).
    shared_gpu: bool | None = None


class ResourceUsage(ResourceContext):
    """Bản ghi nội bộ có attribution; các peak dùng GiB và có thể không đo được."""

    schema_version: Literal["1.1", "1.2"] = "1.2"
    started_at: datetime
    completed_at: datetime
    outcome: Outcome
    exit_code: int | None
    duration_seconds: float = Field(ge=0)
    measurement_method: Literal["sampled_process_tree"] = "sampled_process_tree"
    #: True khi gốc cây là chính tiến trình worker (bước chạy trong worker): RAM gồm cả worker.
    includes_runner_process: bool = False
    sample_count: int = Field(ge=0)
    ram_sample_count: int = Field(ge=0)
    vram_sample_count: int = Field(ge=0)
    gpu_sample_count: int = Field(ge=0)
    scratch_sample_count: int = Field(ge=0)
    peak_ram_gb: float | None = Field(default=None, ge=0)
    #: Tổng VRAM NVIDIA báo cho các PID của cây; None khi không PID nào được báo.
    peak_vram_gb: float | None = Field(default=None, ge=0)
    #: Mức đã dùng của cả GPU worker được ghim, trước khi chạy và cao nhất khi chạy (gồm tiến trình khác).
    gpu_used_before_gb: float | None = Field(default=None, ge=0)
    peak_gpu_used_gb: float | None = Field(default=None, ge=0)
    peak_scratch_gb: float | None = Field(default=None, ge=0)
    #: Mức trống thấp nhất của GPU worker được ghim và RAM cả máy trong lúc chạy.
    min_gpu_free_gb: float | None = Field(default=None, ge=0)
    min_ram_available_gb: float | None = Field(default=None, ge=0)
    #: Tool lỗi trong lúc GPU hoặc RAM gần cạn: nhiều khả năng chết vì hết bộ nhớ (suy luận, không chắc).
    exhausted: bool = False
    headroom_before: dict[str, float | None]


def _tree_memory(root: int, tracked: dict[int, int], proc_root: Path = PROC_ROOT) -> dict[int, float] | None:
    """RSS từng PID của cây gốc `root`; shared pages có thể được đếm ở nhiều PID.

    `tracked` (PID → thời điểm khởi động) được cập nhật tại chỗ: tiến trình đã thấy
    trong cây vẫn được theo dõi sau khi cha thoát và nó bị gán lại cho init. Thành viên
    process group của `root` cũng được tính, để bắt con mồ côi ngay từ mẫu đầu.
    """
    table = process_table(proc_root)
    if table is None:
        return None
    alive = {pid for pid, started in tracked.items() if pid in table and table[pid].started == started}
    grouped = {entry.pid for entry in table.values() if entry.group == root}
    members = process_tree(table, {root} | alive | grouped)
    tracked.clear()
    tracked.update({pid: table[pid].started for pid in members})
    memory = {pid: value for pid in members if (value := resident_gb(pid, proc_root)) is not None}
    return memory or None


def _tree_vram(pids: set[int]) -> float | None:
    """Chỉ cộng allocations NVIDIA báo cho PID của cây, không dùng tổng VRAM máy."""
    if not pids:
        return None
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        amounts: list[float] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            pid, value = line.split(",", 1)
            if int(pid.strip()) in pids:
                amount = float(value.strip())
                if amount < 0 or not math.isfinite(amount):
                    return None
                amounts.append(amount / 1024)
        return sum(amounts) if amounts else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _gpu() -> GpuReading | None:
    """Số đo tức thời của GPU worker được ghim; None khi không xác định được GPU."""
    return bound_gpu()


def _ram_available() -> float | None:
    """RAM còn dùng được của cả máy (GiB)."""
    return ram_available_gb()


def _scratch_gb(workspace: Path) -> float | None:
    """Dung lượng file thường trong workspace; không follow symlink, không tính resume/cache."""
    errors: list[OSError] = []
    total = 0
    for parent, _, names in os.walk(workspace, followlinks=False, onerror=errors.append):
        for name in names:
            try:
                info = (Path(parent) / name).stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as error:
                errors.append(error)
            else:
                if stat.S_ISREG(info.st_mode):
                    total += info.st_size
    return None if errors else total / 1024**3


class ResourceSampler:
    """Collector best effort theo công cụ; caller poll và finish cả khi tool lỗi/hủy.

    `exhaustion_ratio` là ngưỡng "gần cạn" (cùng `danger_ratio` của cấu hình ước lượng):
    tool lỗi sau khi GPU hoặc RAM đã dùng quá tỉ lệ này thì bản ghi được đánh dấu `exhausted`.
    """

    def __init__(
        self,
        context: ResourceContext,
        *,
        workspace: Path,
        worker_root: Path,
        exhaustion_ratio: float | None = None,
        ram_total_gb: float | None = None,
    ) -> None:
        self.context = context
        self.workspace = workspace
        self.exhaustion_ratio = exhaustion_ratio
        self.ram_total = ram_total_gb
        self.headroom = measure_live_headroom(worker_root)
        gpu = _gpu()
        self.gpu_before = gpu.used_gb if gpu is not None else None
        self.gpu_total = gpu.total_gb if gpu is not None else None
        if gpu is not None and context.gpu_name is None:
            self.context = context.model_copy(update={"gpu_name": gpu.name})
        self.started_at = datetime.now(UTC)
        self.started = time.monotonic()
        self.samples = 0
        self.tracked: dict[int, int] = {}
        self.includes_runner = False
        self.counts = {"ram": 0, "vram": 0, "gpu": 0, "scratch": 0}
        self.peaks: dict[str, float | None] = {"ram": None, "vram": None, "gpu": None, "scratch": None}
        self.lows: dict[str, float | None] = {"gpu_free": None, "ram_available": None}

    def sample(self, root: int) -> None:
        """Lấy mẫu sau cùng cũng hợp lệ khi process vừa thoát (chỉ còn disk và mức GPU)."""
        self.includes_runner = self.includes_runner or root == os.getpid()
        memory = _tree_memory(root, self.tracked)
        gpu = _gpu()
        values = {
            "ram": sum(memory.values()) if memory else None,
            "vram": _tree_vram(set(memory or {})),
            "gpu": gpu.used_gb if gpu is not None else None,
            "scratch": _scratch_gb(self.workspace),
        }
        self.samples += 1
        for key, value in values.items():
            if value is not None:
                self.counts[key] += 1
                self.peaks[key] = max(value, self.peaks[key] or 0)
        for key, low in (("gpu_free", gpu.free_gb if gpu is not None else None), ("ram_available", _ram_available())):
            if low is not None:
                self.lows[key] = low if self.lows[key] is None else min(low, self.lows[key])  # type: ignore[type-var]

    def _exhausted(self, outcome: Outcome) -> bool:
        """Tool lỗi và phần trống thấp nhất đã xuống dưới (1 − ngưỡng) của tổng."""
        if outcome != "failed" or self.exhaustion_ratio is None:
            return False
        spare = 1 - self.exhaustion_ratio
        checks = ((self.lows["gpu_free"], self.gpu_total), (self.lows["ram_available"], self.ram_total))
        return any(low is not None and total is not None and low <= total * spare for low, total in checks)

    def finish(self, outcome: Outcome, exit_code: int | None) -> ResourceUsage:
        """Append record nội bộ; caller xử lý lỗi disk, không làm thay đổi job state."""
        usage = ResourceUsage(
            **self.context.model_dump(),
            started_at=self.started_at,
            completed_at=datetime.now(UTC),
            outcome=outcome,
            exit_code=exit_code,
            duration_seconds=max(0, time.monotonic() - self.started),
            includes_runner_process=self.includes_runner,
            sample_count=self.samples,
            ram_sample_count=self.counts["ram"],
            vram_sample_count=self.counts["vram"],
            gpu_sample_count=self.counts["gpu"],
            scratch_sample_count=self.counts["scratch"],
            peak_ram_gb=self.peaks["ram"],
            peak_vram_gb=self.peaks["vram"],
            gpu_used_before_gb=self.gpu_before,
            peak_gpu_used_gb=self.peaks["gpu"],
            peak_scratch_gb=self.peaks["scratch"],
            min_gpu_free_gb=self.lows["gpu_free"],
            min_ram_available_gb=self.lows["ram_available"],
            exhausted=self._exhausted(outcome),
            headroom_before=self.headroom,
        )
        with (self.workspace / "resource-usage.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(usage.model_dump_json() + "\n")
        return usage


@contextmanager
def sampled_section(
    sampler: ResourceSampler | None,
    *,
    on_error: Callable[[Exception], None],
    interval_seconds: float = 2.0,
) -> Iterator[None]:
    """Lấy mẫu cây tiến trình của chính worker trong lúc chạy một bước nằm trong worker.

    Dùng cho bước tách vật thể: nó gọi SAM2/gsplat/LaMa bằng subprocess ngay trong
    tiến trình worker, không qua `_run_tool`. Luồng nền chỉ đo; mọi lỗi đo đi qua
    `on_error` và không bao giờ làm hỏng bước đang chạy.
    """
    if sampler is None:
        yield
        return
    stop = Event()

    def loop() -> None:
        while True:
            try:
                sampler.sample(os.getpid())
            except Exception as error:  # noqa: BLE001 - ranh giới đo: không để luồng nền chết im lặng
                on_error(error)
            if stop.wait(interval_seconds):
                return

    thread = Thread(target=loop, name="resource-sampler", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=interval_seconds + 10)
