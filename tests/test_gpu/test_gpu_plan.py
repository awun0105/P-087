"""Chia worker theo GPU (scripts/gpu/gpu_plan.py): đọc nvidia-smi/vulkaninfo, ghép UUID, chia theo VRAM."""

import json

from scripts.gpu.gpu_plan import Gpu, parse_nvidia_smi, parse_vulkan_discrete_uuids, plan, with_wgpu_indices

SMI_T4X2 = """0, GPU-aaaaaaaa-0000-0000-0000-000000000001, Tesla T4, 15360, 15100
1, GPU-bbbbbbbb-0000-0000-0000-000000000002, Tesla T4, 15360, 15100
"""
VULKAN_T4X2 = """
GPU0:
	deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
	deviceName         = Tesla T4
	deviceUUID         = bbbbbbbb-0000-0000-0000-000000000002
GPU1:
	deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
	deviceName         = Tesla T4
	deviceUUID         = aaaaaaaa-0000-0000-0000-000000000001
GPU2:
	deviceType         = PHYSICAL_DEVICE_TYPE_CPU
	deviceName         = llvmpipe
	deviceUUID         = 6d657361-3235-2e32-2e38-2d3075627500
"""


def _t4x2() -> list[Gpu]:
    return with_wgpu_indices(parse_nvidia_smi(SMI_T4X2), parse_vulkan_discrete_uuids(VULKAN_T4X2))


def _plan(gpus: list[Gpu], train: float = 2.2, **overrides: float) -> list[tuple[int | None, dict[str, str]]]:
    options = {"jobs": 64, "ram_gb": 256.0, "job_ram_gb": 7.0, "cores": 64, **overrides}
    result = plan(gpus, train, base_brush_environment='{"RUST_LOG":"info"}', **options)  # type: ignore[arg-type]
    return [(slot.gpu_index, slot.environment) for slot in result.slots]


def test_uuid_matching_follows_vulkan_order_not_nvidia_smi_order() -> None:
    first, second = _t4x2()
    # Vulkan liệt kê GPU 1 trước GPU 0: thứ tự DiscreteGpu(N) phải theo Vulkan, bỏ qua thiết bị không rời.
    assert (first.index, first.wgpu_discrete_index) == (0, 1)
    assert (second.index, second.wgpu_discrete_index) == (1, 0)
    assert round(first.total_gb, 1) == 15.0


def test_two_gpus_share_workers_evenly_and_pin_both_runtimes() -> None:
    slots = _plan(_t4x2())
    # Mỗi job ~5 GB (4 GB tách vật × 1,25): mỗi T4 chứa 2 job (14,7 GB trống) → 4 worker, xen kẽ hai GPU.
    assert [gpu for gpu, _ in slots] == [0, 1, 0, 1]
    gpu, environment = slots[1]
    assert environment["CUDA_VISIBLE_DEVICES"] == "1"
    brush = json.loads(environment["R2S_BRUSH_ENVIRONMENT"])
    assert brush == {"RUST_LOG": "info", "CUBECL_WGPU_DEFAULT_DEVICE": "DiscreteGpu(0)"}


def test_single_gpu_keeps_default_environment() -> None:
    (gpu,) = parse_nvidia_smi("0, GPU-cccccccc-0000-0000-0000-000000000003, RTX 4090, 24564, 24000\n")
    slots = _plan([gpu])
    assert len(slots) == 4 and all(environment == {} for _, environment in slots)


def test_limits_by_jobs_cpu_and_ram() -> None:
    assert len(_plan(_t4x2(), jobs=1)) == 1
    assert len(_plan(_t4x2(), cores=4)) == 2  # Kaggle T4×2: 4 nhân → mỗi GPU một job
    assert len(_plan(_t4x2(), ram_gb=20.0)) == 2


def test_heavy_job_gets_fewer_slots_and_busy_gpu_is_skipped() -> None:
    # Preset nặng ~10,3 GB train → 12,9 GB với phần dư: mỗi T4 chỉ chứa một job.
    assert [gpu for gpu, _ in _plan(_t4x2(), train=10.3)] == [0, 1]
    busy = [Gpu(0, "GPU-a", "T4", 15.0, 2.0, 0), Gpu(1, "GPU-b", "T4", 15.0, 14.7, 1)]
    assert [gpu for gpu, _ in _plan(busy)] == [1, 1]


def test_no_gpu_or_too_little_vram_still_runs_one_worker() -> None:
    assert _plan([]) == [(None, {})]
    tiny = [Gpu(0, "GPU-a", "T2000", 4.0, 2.2, 0)]
    result = plan(tiny, 2.2, jobs=5, ram_gb=32.0, job_ram_gb=7.0, cores=12)
    assert len(result.slots) == 1 and "thiếu VRAM" in result.reason


def test_unknown_vulkan_mapping_pins_torch_only() -> None:
    gpus = with_wgpu_indices(parse_nvidia_smi(SMI_T4X2), [])
    _, environment = _plan(gpus)[0]
    assert environment == {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "CUDA_VISIBLE_DEVICES": "0"}
