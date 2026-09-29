"""Worker tự đo cấu hình máy và ghi vào DB; API đọc bản mới nhất để kiểm thông số.

Xử lý chạy trên máy worker (GPU server) nên cần số đo của chính máy đó, không
phải của máy người dùng đang mở trình duyệt.
"""

import os
import shutil
import socket
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing.models import MachineCapability

#: Số đo cũ hơn mức này coi như worker không còn chạy.
CAPABILITY_TTL = timedelta(minutes=15)


def _gpu() -> tuple[str | None, float | None]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    rows = [line.split(",") for line in result.stdout.strip().splitlines() if line.strip()]
    if not rows:
        return None, None
    # Brush dùng một GPU; lấy GPU có nhiều VRAM nhất.
    name, memory = max(rows, key=lambda row: float(row[1]))
    return name.strip(), round(float(memory) / 1024, 2)


def _ram_gb() -> float:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1024**2, 2)
    except OSError:
        pass
    pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
    return round(pages * size / 1024**3, 2)


def probe(worker_root: Path) -> MachineCapability:
    """Đo GPU/VRAM (nvidia-smi), CPU, RAM và ổ trống tại thư mục làm việc của worker."""
    gpu_name, vram = _gpu()
    worker_root.mkdir(parents=True, exist_ok=True)
    return MachineCapability(
        worker_id=f"{socket.gethostname()}:{os.getpid()}",
        measured_at=datetime.now(UTC),
        gpu_name=gpu_name,
        vram_total_gb=vram,
        cpu_count=os.cpu_count() or 1,
        ram_total_gb=_ram_gb(),
        disk_free_gb=round(shutil.disk_usage(worker_root).free / 1024**3, 2),
    )


def record(database: RuntimeDatabase, capability: MachineCapability) -> None:
    """Ghi/ghi đè số đo của worker này (upsert theo worker_id)."""
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_workers(worker_id, payload) VALUES (?, ?) "
            "ON CONFLICT(worker_id) DO UPDATE SET payload=excluded.payload",
            (capability.worker_id, capability.model_dump_json()),
        )


def latest(database: RuntimeDatabase, now: datetime | None = None) -> MachineCapability | None:
    """Số đo mới nhất còn hạn; None khi chưa có worker nào đang chạy."""
    with database.transaction() as tx:
        rows = tx.execute("SELECT payload FROM r2s_workers").fetchall()
    fresh = [
        capability
        for capability in (MachineCapability.model_validate_json(row[0]) for row in rows)
        if (now or datetime.now(UTC)) - capability.measured_at <= CAPABILITY_TTL
    ]
    return max(fresh, key=lambda item: item.measured_at, default=None)
