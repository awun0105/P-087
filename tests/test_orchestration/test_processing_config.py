"""File cấu hình xử lý chung: validate thông số, dựng config job, ước lượng tài nguyên."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing import (
    ProcessingConfigError,
    build_job_config,
    config_bytes,
    evaluate,
    load_presets,
    maximum_for_machine,
    preset_values,
)
from src.services.orchestration.processing.capability import latest, record
from src.services.orchestration.processing.models import MachineCapability

ROOT = Path(__file__).resolve().parents[2]
PRESETS = ROOT / "configs/product/processing_presets_v1.json"
NOW = datetime(2026, 9, 29, 9, tzinfo=UTC)


def _machine(vram: float | None = 24, ram: float = 128, disk: float = 500, cpu: int = 32) -> MachineCapability:
    return MachineCapability(
        worker_id="gpu-1",
        measured_at=NOW,
        gpu_name="GPU",
        vram_total_gb=vram,
        cpu_count=cpu,
        ram_total_gb=ram,
        disk_free_gb=disk,
    )


def test_presets_file_is_valid_and_minimum_fits_a_modest_gpu() -> None:
    presets, checksum = load_presets(PRESETS)
    assert checksum.startswith("sha256:")
    minimum = preset_values(presets, "minimum_quality")
    assert not evaluate(presets, minimum, _machine(vram=8, ram=32, disk=100)).blocking


def test_out_of_range_missing_and_wrong_type_are_rejected() -> None:
    presets, checksum = load_presets(PRESETS)
    params = preset_values(presets, "minimum_quality")
    for key, value in (("brush.max_splats", 10), ("colmap.camera_model", "FISHEYE"), ("sampling.max_frames", 12.5)):
        with pytest.raises(ProcessingConfigError, match=key):
            build_job_config(presets, checksum, {**params, key: value}, None)
    del params["brush.sh_degree"]
    with pytest.raises(ProcessingConfigError, match="thiếu"):
        build_job_config(presets, checksum, params, None)


def test_job_config_merges_fixed_values_and_is_byte_stable() -> None:
    presets, checksum = load_presets(PRESETS)
    params = preset_values(presets, "minimum_quality")
    config = build_job_config(presets, checksum, params, _machine(cpu=64))
    assert config.colmap["num_threads"] == presets.fixed.colmap_max_threads
    assert config.colmap["max_image_size"] == params["colmap.max_image_size"]
    assert config.colmap["single_camera"] is True and config.brush["refine_every"] == 200
    assert config.sampling == {"sample_fps": 3, "max_frames": 300}
    assert config_bytes(config) == config_bytes(build_job_config(presets, checksum, dict(params), _machine(cpu=64)))


def test_small_gpu_marks_heavy_parameters_red_and_blocks() -> None:
    presets, _ = load_presets(PRESETS)
    evaluation = evaluate(presets, preset_values(presets, "maximum"), _machine(vram=4, ram=16, disk=20))
    assert evaluation.blocking
    vram = next(item for item in evaluation.resources if item.resource == "vram")
    assert vram.status == "danger" and "crash" in vram.message
    marked = {item.key: item.status for item in evaluation.parameters}
    assert marked["brush.max_splats"] == "danger" and marked["brush.max_resolution"] == "danger"
    assert marked["brush.total_train_iters"] == "ok"


def test_unknown_machine_is_not_reported_as_safe() -> None:
    presets, _ = load_presets(PRESETS)
    evaluation = evaluate(presets, preset_values(presets, "maximum"), None)
    assert {item.status for item in evaluation.resources} == {"unknown"}
    assert not evaluation.blocking
    assert maximum_for_machine(presets, None) == preset_values(presets, "minimum_quality")


def test_live_headroom_drives_estimate_and_maximum_but_busy_gpu_can_enqueue() -> None:
    presets, _ = load_presets(PRESETS)
    live = _machine().model_copy(update={"headroom_measured": True, "vram_free_gb": 0.1, "ram_available_gb": 100})
    params = preset_values(presets, "minimum_quality")
    evaluation = evaluate(presets, params, live)
    gpu = next(item for item in evaluation.resources if item.resource == "vram")
    assert gpu.available_gb == 0.1 and gpu.status == "danger" and "job sẽ chờ" in gpu.message
    assert not evaluation.blocking  # Cấu hình vừa capacity máy, GPU chỉ đang bận.
    disk_busy = live.model_copy(update={"disk_free_gb": 0.1})
    assert not evaluate(presets, params, disk_busy).blocking
    too_small = live.model_copy(update={"vram_total_gb": 0.1})
    assert evaluate(presets, params, too_small).blocking
    # Mốc rảnh đã đo nhưng thiếu VRAM (không xác định được GPU): không suy Maximum từ số đo thiếu.
    unknown = live.model_copy(
        update={"vram_free_gb": None, "idle_measured_at": NOW, "idle_ram_available_gb": 100, "idle_disk_free_gb": 500}
    )
    assert maximum_for_machine(presets, unknown) == params
    assert (
        next(item for item in evaluate(presets, params, unknown).resources if item.resource == "vram").status
        == "unknown"
    )


def test_maximum_uses_idle_baseline_not_what_a_running_job_left_free() -> None:
    """Worker đang train job khác: phần trống tức thời tụt, Maximum vẫn theo mốc lúc máy rảnh."""
    presets, _ = load_presets(PRESETS)
    idle = _machine(vram=4, ram=31, disk=20).model_copy(
        update={
            "headroom_measured": True,
            "vram_free_gb": 3.6,
            "ram_available_gb": 24.0,
            "idle_measured_at": NOW,
            "idle_vram_free_gb": 3.6,
            "idle_ram_available_gb": 24.0,
            "idle_disk_free_gb": 20.0,
        }
    )
    busy = idle.model_copy(update={"vram_free_gb": 0.6, "ram_available_gb": 6.0, "disk_free_gb": 12.0})
    best = maximum_for_machine(presets, idle)
    assert maximum_for_machine(presets, busy) == best
    minimum = preset_values(presets, "minimum_quality")
    assert float(best["brush.max_splats"]) >= float(minimum["brush.max_splats"])
    # Cấu hình đó hiện đỏ vì máy đang bận, nhưng không bị chặn: job chờ rồi chạy với nguyên cấu hình.
    evaluation = evaluate(presets, best, busy)
    assert not evaluation.blocking
    assert any(item.status == "danger" and "job sẽ chờ" in item.message for item in evaluation.resources)
    # Mốc rảnh nhỏ hơn tổng (thứ khác trên máy luôn chiếm một phần): Maximum không vượt mốc rảnh.
    total_only = _machine(vram=4, ram=31, disk=20)
    assert float(best["brush.max_splats"]) <= float(maximum_for_machine(presets, total_only)["brush.max_splats"])


def test_disk_larger_than_the_whole_drive_blocks_but_a_full_drive_only_waits() -> None:
    presets, _ = load_presets(PRESETS)
    params = preset_values(presets, "maximum")
    machine = _machine().model_copy(
        update={"headroom_measured": True, "vram_free_gb": 48, "ram_available_gb": 256, "disk_free_gb": 0.5}
    )
    roomy = machine.model_copy(update={"disk_total_gb": 500.0})
    disk = next(item for item in evaluate(presets, params, roomy).resources if item.resource == "disk")
    assert disk.status == "danger" and not evaluate(presets, params, roomy).blocking
    tiny = machine.model_copy(update={"disk_total_gb": 10.0})
    assert evaluate(presets, params, tiny).blocking


def test_shortage_that_persists_when_idle_is_explained_differently() -> None:
    presets, _ = load_presets(PRESETS)
    params = preset_values(presets, "minimum_quality")
    machine = _machine().model_copy(
        update={
            "headroom_measured": True,
            "vram_free_gb": 0.5,
            "ram_available_gb": 100,
            "idle_measured_at": NOW,
            "idle_vram_free_gb": 0.5,
            "idle_ram_available_gb": 100,
            "idle_disk_free_gb": 500,
        }
    )
    gpu = next(item for item in evaluate(presets, params, machine).resources if item.resource == "vram")
    assert "lúc máy xử lý rảnh cũng không đủ" in gpu.message and not evaluate(presets, params, machine).blocking


@pytest.mark.parametrize(
    "machine",
    [_machine(), _machine(vram=4, ram=31, disk=12), _machine(vram=2, ram=8, disk=3, cpu=4)],
)
def test_maximum_for_machine_stays_below_warning_and_valid(machine: MachineCapability) -> None:
    presets, _ = load_presets(PRESETS)
    best = maximum_for_machine(presets, machine)
    presets.validate_params(best)
    statuses = {item.resource: item.status for item in evaluate(presets, best, machine).resources}
    assert set(statuses.values()) <= {"ok"}, statuses


def test_big_gpu_gets_full_maximum_and_small_gpu_scales_everything_down_together() -> None:
    presets, _ = load_presets(PRESETS)
    assert maximum_for_machine(presets, _machine()) == preset_values(presets, "maximum")
    small = maximum_for_machine(presets, _machine(vram=4, ram=31, disk=12))
    minimum = preset_values(presets, "minimum_quality")
    for key in ("brush.max_splats", "brush.max_resolution", "sampling.max_frames"):
        assert float(small[key]) >= float(minimum[key])


def test_capability_record_and_latest_ignore_stale_workers(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    record(database, _machine().model_copy(update={"worker_id": "old", "measured_at": NOW - timedelta(hours=1)}))
    assert latest(database, now=NOW) is None
    record(database, _machine())
    record(database, _machine(vram=48))
    current = latest(database, now=NOW + timedelta(minutes=1))
    assert current is not None and current.vram_total_gb == 48
