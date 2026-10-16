"""Dò GPU của máy và chia worker cho từng GPU (Kaggle T4×2, máy thuê nhiều GPU trên vast.ai, máy một GPU).

    set -a; source <file env>; set +a
    python -m scripts.gpu.gpu_plan                 # in bảng GPU + kế hoạch chia worker
    python -m scripts.gpu.gpu_plan --jobs 4 --json # kế hoạch dạng JSON cho script khác đọc

Mỗi worker được **ghim trọn một job vào một GPU** bằng biến môi trường, không sửa code pipeline:

- các bước torch (SAM2, gán nhãn bằng gsplat, vá nền LaMa): `CUDA_VISIBLE_DEVICES=<chỉ số nvidia-smi>`;
- Brush (train 3DGS qua Vulkan): `CUBECL_WGPU_DEFAULT_DEVICE=DiscreteGpu(<thứ tự GPU rời trong Vulkan>)`, ghép
  với chỉ số nvidia-smi qua UUID thiết bị (Vulkan `deviceUUID` = UUID của nvidia-smi bỏ tiền tố `GPU-`).

Số worker trên mỗi GPU = VRAM trống của GPU đó chia cho nhu cầu một job (có chừa dư để không tràn VRAM),
rồi chặn theo RAM, số nhân CPU và số job. Không GPU nào đủ chỗ cho một job thì vẫn chạy một worker trên GPU
trống nhất và ghi rõ là thiếu VRAM.

Đã kiểm trên máy một GPU rời (2026-10-01): Brush nghe theo `CUBECL_WGPU_DEFAULT_DEVICE`, UUID hai bên khớp.
CHƯA chạy trên máy hai GPU rời: thứ tự `DiscreteGpu(N)` suy từ thứ tự liệt kê của `vulkaninfo`.
`splat-transform` (nén SOG, dựng voxel — ngắn) vẫn dùng GPU mặc định của nó.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass

from src.runtime_env import runtime_env

#: VRAM cho bước tách theo vật. Giả định thận trọng: lần chạy thật trên T2000 4 GB (scene ~330k Gaussian)
#: nằm gọn trong 4 GB; chưa đo trên GPU lớn với scene lớn hơn.
OBJECTIFY_VRAM_GB = 4.0
#: Chừa 25 % để hai job cùng ở đỉnh không tràn VRAM.
VRAM_HEADROOM = 1.25
#: Một job cần ít nhất khoảng 2 nhân (COLMAP, CoACD chạy CPU; Brush và torch chủ yếu dùng GPU). Kaggle T4×2
#: chỉ có 4 nhân: mức này cho phép 2 job song song, mỗi GPU một job.
CORES_PER_JOB = 2


@dataclass(frozen=True)
class Gpu:
    """Một GPU NVIDIA: chỉ số nvidia-smi, VRAM (GB) và thứ tự trong các GPU rời của Vulkan (None = chưa rõ)."""

    index: int
    uuid: str
    name: str
    total_gb: float
    free_gb: float
    wgpu_discrete_index: int | None = None


@dataclass(frozen=True)
class WorkerSlot:
    """Một worker và GPU nó được ghim vào, kèm biến môi trường cần đặt khi khởi động worker đó."""

    worker: int
    gpu_index: int | None
    environment: dict[str, str]


@dataclass(frozen=True)
class Plan:
    """Kế hoạch chia worker + lý do, để in ra cho người chạy và ghi log."""

    slots: list[WorkerSlot]
    per_job_vram_gb: float
    reason: str


def _run(command: list[str]) -> str | None:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def parse_nvidia_smi(text: str) -> list[Gpu]:
    """Đọc `nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.free --format=csv,noheader,nounits`."""
    gpus = []
    for line in text.strip().splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            continue
        gpus.append(Gpu(int(fields[0]), fields[1], fields[2], float(fields[3]) / 1024, float(fields[4]) / 1024))
    return gpus


def parse_vulkan_discrete_uuids(text: str) -> list[str]:
    """UUID của các GPU rời theo đúng thứ tự `vulkaninfo --summary` liệt kê (thứ tự `DiscreteGpu(N)`)."""
    uuids, discrete = [], False
    for line in text.splitlines():
        if "deviceType" in line:
            discrete = "DISCRETE_GPU" in line
        match = re.search(r"deviceUUID\s*=\s*([0-9a-fA-F-]{36})", line)
        if match and discrete:
            uuids.append(match.group(1).lower())
    return uuids


def with_wgpu_indices(gpus: list[Gpu], discrete_uuids: list[str]) -> list[Gpu]:
    """Gắn thứ tự GPU rời của Vulkan cho từng GPU bằng UUID; không khớp thì để None."""
    order = {uuid: position for position, uuid in enumerate(discrete_uuids)}
    return [
        Gpu(gpu.index, gpu.uuid, gpu.name, gpu.total_gb, gpu.free_gb, order.get(gpu.uuid.lower().removeprefix("gpu-")))
        for gpu in gpus
    ]


def detect() -> list[Gpu]:
    """GPU NVIDIA của máy này; rỗng nếu không có `nvidia-smi`."""
    text = _run(["nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.free", "--format=csv,noheader,nounits"])
    if text is None:
        return []
    vulkan = _run(["vulkaninfo", "--summary"])
    return with_wgpu_indices(parse_nvidia_smi(text), parse_vulkan_discrete_uuids(vulkan or ""))


def worker_environment(gpu: Gpu, gpu_count: int, base_brush_environment: str | None) -> dict[str, str]:
    """Biến môi trường ghim một worker vào `gpu`. Máy một GPU thì không đổi gì (hành vi mặc định đã đúng)."""
    if gpu_count < 2:
        return {}
    # CUDA mặc định xếp GPU theo tốc độ; ép theo thứ tự PCI để chỉ số trùng với nvidia-smi
    # (worker cũng đo VRAM của đúng chỉ số này trước khi nhận job).
    environment = {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "CUDA_VISIBLE_DEVICES": str(gpu.index)}
    if gpu.wgpu_discrete_index is not None:
        brush = json.loads(base_brush_environment or "{}")
        brush["CUBECL_WGPU_DEFAULT_DEVICE"] = f"DiscreteGpu({gpu.wgpu_discrete_index})"
        environment["R2S_BRUSH_ENVIRONMENT"] = json.dumps(brush)
    return environment


def plan(
    gpus: list[Gpu],
    train_vram_gb: float,
    *,
    jobs: int,
    ram_gb: float,
    job_ram_gb: float,
    cores: int,
    base_brush_environment: str | None = None,
) -> Plan:
    """Chia worker: mỗi lần gán thêm một worker cho GPU đang còn nhiều VRAM trống nhất mà vẫn đủ chỗ."""
    per_job = max(train_vram_gb, OBJECTIFY_VRAM_GB) * VRAM_HEADROOM
    if not gpus:
        return Plan([WorkerSlot(0, None, {})], per_job, "không thấy GPU NVIDIA; chạy một worker")
    limits = {
        "RAM": int(ram_gb // max(job_ram_gb, 1.0)),
        "CPU": cores // CORES_PER_JOB,
        "số job": jobs,
    }
    cap_name = min(limits, key=lambda name: limits[name])
    cap = max(1, limits[cap_name])
    remaining = {gpu.index: gpu.free_gb for gpu in gpus}
    by_index = {gpu.index: gpu for gpu in gpus}
    chosen: list[Gpu] = []
    while len(chosen) < cap:
        index = max(remaining, key=lambda key: remaining[key])
        if remaining[index] < per_job:
            break
        remaining[index] -= per_job
        chosen.append(by_index[index])
    if not chosen:
        best = max(gpus, key=lambda gpu: gpu.free_gb)
        chosen, reason = (
            [best],
            f"không GPU nào trống đủ {per_job:.1f} GB cho một job; chạy một worker, có thể thiếu VRAM",
        )
    else:
        vram_slots = sum(int(gpu.free_gb // per_job) for gpu in gpus)
        bound = "VRAM" if len(chosen) == vram_slots and vram_slots <= cap else cap_name
        reason = f"mỗi job ~{per_job:.1f} GB VRAM; chặn bởi {bound}"
    slots = [
        WorkerSlot(number, gpu.index, worker_environment(gpu, len(gpus), base_brush_environment))
        for number, gpu in enumerate(chosen)
    ]
    return Plan(slots, per_job, reason)


def plan_for_machine(jobs: int, processing: dict | None = None) -> tuple[list[Gpu], Plan]:
    """Dò máy này và lập kế hoạch theo file cấu hình xử lý của stack (`PRODUCT_PROCESSING_CONFIG`)."""
    from src.config import get_settings
    from src.services.orchestration.processing import load_presets
    from src.services.orchestration.processing.config import preset_values
    from src.services.orchestration.processing.container_limits import (
        effective_cpu_count,
        memory_limit_gb,
    )
    from src.services.orchestration.processing.resources import estimate_gb

    gpus = detect()
    need = {"vram": OBJECTIFY_VRAM_GB, "ram": 8.0}
    config = get_settings().product_processing_config
    if config is not None:
        presets, _ = load_presets(config)
        need = estimate_gb(presets.resource_model, {**preset_values(presets, "minimum_quality"), **(processing or {})})
    physical_ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    cgroup_ram = memory_limit_gb()
    ram_gb = min(physical_ram, cgroup_ram) if cgroup_ram is not None else physical_ram
    return gpus, plan(
        gpus,
        need["vram"],
        jobs=jobs,
        ram_gb=ram_gb,
        job_ram_gb=need["ram"],
        cores=effective_cpu_count(),
        base_brush_environment=runtime_env(os.environ, "R2S_BRUSH_ENVIRONMENT"),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: in GPU và kế hoạch chia worker."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jobs", type=int, default=64, help="số job sẽ chạy (mặc định: không giới hạn theo job)")
    parser.add_argument("--json", action="store_true", help="in kế hoạch dạng JSON")
    args = parser.parse_args(argv)
    gpus, result = plan_for_machine(args.jobs)
    if args.json:
        print(json.dumps({"gpus": [asdict(gpu) for gpu in gpus], "plan": asdict(result)}, ensure_ascii=False))
        return 0
    for gpu in gpus:
        vulkan = f"DiscreteGpu({gpu.wgpu_discrete_index})" if gpu.wgpu_discrete_index is not None else "chưa ghép được"
        print(f"GPU {gpu.index}: {gpu.name} · {gpu.free_gb:.1f}/{gpu.total_gb:.1f} GB trống · Vulkan {vulkan}")
    print(f"{len(result.slots)} worker — {result.reason}")
    for slot in result.slots:
        print(f"  worker {slot.worker} → GPU {slot.gpu_index} {slot.environment or '(mặc định)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
