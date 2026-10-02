"""Telemetry sampled của CLI process group, lưu nội bộ theo attempt.

Không sửa shared manifest/benchmark protocol. Peak là cực đại quan sát được qua
polling; NVIDIA không báo WGPU allocation thì VRAM giữ None, không bịa usage.
"""

import math
import os
import stat
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.services.orchestration.processing.capability import measure_live_headroom

Outcome = Literal["completed", "failed", "cancelled", "timeout"]


class ResourceContext(BaseModel):
    """Bind mẫu đo với đúng CLI execution/config, không phải competing job state."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    job_id: str
    attempt_id: str
    tool: str
    config_checksum: str
    runtime_manifest_checksum: str


class ResourceUsage(ResourceContext):
    """Bản ghi nội bộ có attribution; các peak dùng GiB và có thể không đo được."""

    schema_version: Literal["1.0"] = "1.0"
    started_at: datetime
    completed_at: datetime
    outcome: Outcome
    exit_code: int | None
    duration_seconds: float = Field(ge=0)
    measurement_method: Literal["sampled_process_group"] = "sampled_process_group"
    sample_count: int = Field(ge=0)
    ram_sample_count: int = Field(ge=0)
    vram_sample_count: int = Field(ge=0)
    scratch_sample_count: int = Field(ge=0)
    peak_ram_gb: float | None = Field(default=None, ge=0)
    peak_vram_gb: float | None = Field(default=None, ge=0)
    peak_scratch_gb: float | None = Field(default=None, ge=0)
    headroom_before: dict[str, float | None]


def _group_memory(group_id: int, proc_root: Path = Path("/proc")) -> dict[int, float] | None:
    """RSS theo process group (gồm child); shared pages có thể được đếm ở nhiều PID."""
    memory: dict[int, float] = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            # comm có thể chứa dấu cách/ngoặc; các field sau dấu ')' cuối có pgrp ở index 2.
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) != group_id:
                continue
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) / 1024**2
                    if rss >= 0:
                        memory[int(entry.name)] = rss
                    break
        except (OSError, ValueError, IndexError):
            continue  # PID có thể thoát giữa stat và status; sampled metric không phải exact peak.
    return memory or None


def _group_vram(pids: set[int]) -> float | None:
    """Chỉ cộng allocations NVIDIA báo cho PID của group, không dùng tổng VRAM máy."""
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
    """Collector best effort theo CLI; caller poll và finish cả khi tool lỗi/hủy."""

    def __init__(self, context: ResourceContext, *, workspace: Path, worker_root: Path) -> None:
        self.context = context
        self.workspace = workspace
        self.headroom = measure_live_headroom(worker_root)
        self.started_at = datetime.now(UTC)
        self.started = time.monotonic()
        self.samples = 0
        self.counts = {"ram": 0, "vram": 0, "scratch": 0}
        self.peaks: dict[str, float | None] = {"ram": None, "vram": None, "scratch": None}

    def sample(self, process_group: int) -> None:
        """Lấy mẫu sau cùng cũng hợp lệ khi process vừa thoát (chỉ còn disk)."""
        memory = _group_memory(process_group)
        values = {
            "ram": sum(memory.values()) if memory else None,
            "vram": _group_vram(set(memory or {})),
            "scratch": _scratch_gb(self.workspace),
        }
        self.samples += 1
        for key, value in values.items():
            if value is not None:
                self.counts[key] += 1
                self.peaks[key] = max(value, self.peaks[key] or 0)

    def finish(self, outcome: Outcome, exit_code: int | None) -> ResourceUsage:
        """Append record nội bộ; caller xử lý lỗi disk, không làm thay đổi job state."""
        usage = ResourceUsage(
            **self.context.model_dump(),
            started_at=self.started_at,
            completed_at=datetime.now(UTC),
            outcome=outcome,
            exit_code=exit_code,
            duration_seconds=max(0, time.monotonic() - self.started),
            sample_count=self.samples,
            ram_sample_count=self.counts["ram"],
            vram_sample_count=self.counts["vram"],
            scratch_sample_count=self.counts["scratch"],
            peak_ram_gb=self.peaks["ram"],
            peak_vram_gb=self.peaks["vram"],
            peak_scratch_gb=self.peaks["scratch"],
            headroom_before=self.headroom,
        )
        with (self.workspace / "resource-usage.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(usage.model_dump_json() + "\n")
        return usage
