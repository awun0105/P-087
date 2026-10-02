"""Worker tự đo cấu hình máy và ghi vào DB; API đọc bản mới nhất để kiểm thông số.

Xử lý chạy trên máy worker (GPU server) nên cần số đo của chính máy đó, không
phải của máy người dùng đang mở trình duyệt.
"""

import logging
import math
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing.models import MachineCapability

#: Số đo cũ hơn mức này coi như worker không còn chạy.
CAPABILITY_TTL = timedelta(minutes=15)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GpuReading:
    """Một GPU NVIDIA theo `nvidia-smi` (GiB)."""

    index: int
    uuid: str
    name: str
    total_gb: float
    free_gb: float
    used_gb: float


def _query_gpus(timeout: float = 2) -> list[GpuReading] | None:
    """Mọi GPU máy này; None khi không gọi được `nvidia-smi` hoặc output không đọc được."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid,name,memory.total,memory.free,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        gpus: list[GpuReading] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            index, uuid, name, total, free, used = (field.strip() for field in line.split(","))
            amounts = [float(value) / 1024 for value in (total, free, used)]
            if any(not math.isfinite(value) or value < 0 for value in amounts):
                raise ValueError("Invalid VRAM measurement")
            gpus.append(GpuReading(int(index), uuid, name, *amounts))
        return gpus
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        logger.warning("Không đo được GPU cause=%s", type(error).__name__)
        return None


def _select_gpu(gpus: list[GpuReading], visible: str | None) -> GpuReading | None:
    """GPU mà workload của worker này dùng.

    `scripts/gpu/gpu_plan.py` ghim mỗi worker vào một GPU bằng `CUDA_VISIBLE_DEVICES`
    (chỉ số nvidia-smi, đi kèm `CUDA_DEVICE_ORDER=PCI_BUS_ID`); `nvidia-smi` thì luôn
    liệt kê mọi GPU nên phải tự chọn đúng dòng. Mục đầu tiên là thiết bị mặc định của
    torch. Không ghim trên máy nhiều GPU → None: không đoán thiết bị.
    """
    if visible is None:
        return gpus[0] if len(gpus) == 1 else None
    first = visible.split(",")[0].strip()
    if first.isdecimal():
        return next((gpu for gpu in gpus if gpu.index == int(first)), None)
    if first.upper().startswith("GPU-"):
        matches = [gpu for gpu in gpus if gpu.uuid.lower().startswith(first.lower())]
        return matches[0] if len(matches) == 1 else None
    return None


def bound_gpu() -> GpuReading | None:
    """Số đo tức thời của GPU worker này được ghim; None khi không đo hoặc không xác định được."""
    gpus = _query_gpus()
    if not gpus:
        return None
    gpu = _select_gpu(gpus, os.environ.get("CUDA_VISIBLE_DEVICES"))
    if gpu is None:
        logger.info("GPU của worker chưa xác định: máy có %s GPU và worker không được ghim", len(gpus))
    return gpu


def _live_vram_gb() -> float | None:
    """VRAM còn trống của GPU worker được ghim; không xác định được thì unknown, không phải 0."""
    gpu = bound_gpu()
    return gpu.free_gb if gpu is not None else None


def _live_ram_gb() -> float | None:
    """MemAvailable tính cả cache có thể thu hồi, không dùng MemFree/MemTotal."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                value = int(line.split()[1]) / 1024**2
                if value < 0:
                    raise ValueError("Invalid RAM measurement")
                return value
    except (OSError, ValueError, IndexError) as error:
        logger.warning("Không đo được live RAM cause=%s", type(error).__name__)
    return None


def measure_live_headroom(worker_root: Path) -> dict[str, float | None]:
    """Đo VRAM/RAM/đĩa khả dụng tức thời (GiB); probe lỗi trả None, không tạo thư mục.

    Đây là snapshot, không phải reservation hoặc cam kết cấu hình sẽ chạy được.
    VRAM là của GPU worker được ghim (`bound_gpu`); máy nhiều GPU chưa ghim thì unknown.
    """
    try:
        disk = shutil.disk_usage(worker_root).free / 1024**3
    except OSError as error:
        logger.warning("Không đo được live disk cause=%s", type(error).__name__)
        disk = None
    return {"vram_free_gb": _live_vram_gb(), "ram_available_gb": _live_ram_gb(), "disk_free_gb": disk}


def _gpu() -> GpuReading | None:
    """GPU để báo cấu hình máy: GPU được ghim; máy nhiều GPU chưa ghim thì GPU nhiều VRAM nhất (chỉ tổng)."""
    gpus = _query_gpus(timeout=15)
    if not gpus:
        return None
    return _select_gpu(gpus, os.environ.get("CUDA_VISIBLE_DEVICES")) or max(gpus, key=lambda gpu: gpu.total_gb)


def measure_capacity(worker_root: Path) -> dict[str, float | None]:
    """Tổng năng lực máy (GiB) cho VRAM của GPU được ghim, RAM và ổ chứa thư mục worker."""
    gpu = bound_gpu()
    try:
        disk: float | None = shutil.disk_usage(worker_root).total / 1024**3
    except OSError:
        disk = None
    try:
        ram: float | None = _ram_gb()
    except (OSError, ValueError):
        ram = None
    return {"vram": gpu.total_gb if gpu is not None else None, "ram": ram, "disk": disk}


def _ram_gb() -> float:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1024**2, 2)
    except OSError:
        pass
    pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
    return round(pages * size / 1024**3, 2)


def worker_identity() -> tuple[str, str, int]:
    """(worker_id, host, pid) của tiến trình worker này; cùng định danh cho số đo và giữ chỗ."""
    host, pid = socket.gethostname(), os.getpid()
    return f"{host}:{pid}", host, pid


def probe(worker_root: Path, *, idle: bool = False, previous: MachineCapability | None = None) -> MachineCapability:
    """Đo GPU/VRAM (nvidia-smi), CPU, RAM và ổ trống tại thư mục làm việc của worker.

    `idle=True` khi pipeline không dùng máy lúc đo: số đo trống được ghi làm mốc "máy
    rảnh" để tính preset Maximum. Khi bận, mốc rảnh gần nhất trong `previous` được giữ
    lại, vì phần đang trống lúc đó đã bị chính job đang chạy chiếm.
    """
    selected = bound_gpu()
    gpu = selected or _gpu()
    worker_root.mkdir(parents=True, exist_ok=True)
    live = measure_live_headroom(worker_root)
    usage = shutil.disk_usage(worker_root)
    now = datetime.now(UTC)
    baseline: dict[str, object] = {}
    if idle and live["disk_free_gb"] is not None:
        baseline = {
            "idle_measured_at": now,
            "idle_vram_free_gb": live["vram_free_gb"],
            "idle_ram_available_gb": live["ram_available_gb"],
            "idle_disk_free_gb": live["disk_free_gb"],
        }
    elif previous is not None:
        baseline = {
            "idle_measured_at": previous.idle_measured_at,
            "idle_vram_free_gb": previous.idle_vram_free_gb,
            "idle_ram_available_gb": previous.idle_ram_available_gb,
            "idle_disk_free_gb": previous.idle_disk_free_gb,
        }
    return MachineCapability(
        worker_id=worker_identity()[0],
        measured_at=now,
        gpu_name=gpu.name if gpu is not None else None,
        gpu_uuid=selected.uuid if selected is not None else None,
        vram_total_gb=round(gpu.total_gb, 2) if gpu is not None else None,
        cpu_count=os.cpu_count() or 1,
        ram_total_gb=_ram_gb(),
        disk_free_gb=round(usage.free / 1024**3, 2),
        disk_total_gb=round(usage.total / 1024**3, 2),
        headroom_measured=True,
        vram_free_gb=live["vram_free_gb"],
        ram_available_gb=live["ram_available_gb"],
        **baseline,
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
