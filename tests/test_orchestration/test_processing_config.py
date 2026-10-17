"""File cấu hình xử lý chung: validate thông số, dựng config job, ước lượng tài nguyên."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.processing import (
    SFM_KEYS,
    SPLAT_KEYS,
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
from src.services.orchestration.processing.resources import estimate_gb

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


def test_resource_driver_groups_do_not_include_downstream_controls() -> None:
    presets, _ = load_presets(PRESETS)
    all_keys = {spec.key for spec in presets.parameters}
    sfm_set = set(SFM_KEYS)
    splat_set = set(SPLAT_KEYS)

    assert sfm_set.isdisjoint(splat_set), f"Trùng lặp giữa SFM và SPLAT: {sfm_set & splat_set}"
    assert sfm_set | splat_set <= all_keys
    assert all(key.startswith(("sampling.", "colmap.")) for key in sfm_set)
    assert all(key.startswith("brush.") for key in splat_set)
    assert {spec.group for spec in presets.parameters} == {
        "sampling",
        "colmap",
        "brush",
        "geometry",
        "scene",
        "simulation",
    }


@pytest.mark.parametrize(
    ("vram", "ram", "expected"),
    [
        (
            4,
            16,
            {
                "sampling.max_frames": 1200,
                "colmap.max_image_size": 3200,
                "colmap.max_num_features": 16384,
                "brush.max_resolution": 1280,
                "brush.max_splats": 1_200_000,
                "brush.total_train_iters": 31000,
            },
        ),
        (
            6,
            16,
            {
                "sampling.max_frames": 1200,
                "colmap.max_image_size": 3200,
                "colmap.max_num_features": 16384,
                "brush.max_resolution": 1920,
                "brush.max_splats": 2_200_000,
                "brush.total_train_iters": 37000,
            },
        ),
        (
            8,
            16,
            {
                "sampling.max_frames": 1200,
                "colmap.max_image_size": 3200,
                "colmap.max_num_features": 16384,
                "brush.max_resolution": 2400,
                "brush.max_splats": 3_200_000,
                "brush.total_train_iters": 43000,
            },
        ),
        (
            12,
            32,
            {
                "sampling.max_frames": 1200,
                "colmap.max_image_size": 3200,
                "colmap.max_num_features": 16384,
                "brush.max_resolution": 3360,
                "brush.max_splats": 5_000_000,
                "brush.total_train_iters": 54000,
            },
        ),
        (
            24,
            16,
            {
                "sampling.max_frames": 1200,
                "colmap.max_image_size": 3200,
                "colmap.max_num_features": 16384,
                "brush.max_resolution": 3840,
                "brush.max_splats": 6_000_000,
                "brush.total_train_iters": 60000,
            },
        ),
        (
            24,
            8,
            {
                "sampling.max_frames": 880,
                "colmap.max_image_size": 2560,
                "colmap.max_num_features": 13312,
                "brush.max_resolution": 3840,
                "brush.max_splats": 6_000_000,
                "brush.total_train_iters": 60000,
            },
        ),
        (
            4,
            4,
            {
                "sampling.max_frames": 500,
                "colmap.max_image_size": 1920,
                "colmap.max_num_features": 9216,
                "brush.max_resolution": 1280,
                "brush.max_splats": 1_200_000,
                "brush.total_train_iters": 31000,
            },
        ),
    ],
)
def test_maximum_for_machine_two_axis_matrix(vram: float, ram: float, expected: dict[str, int]) -> None:
    presets, _ = load_presets(PRESETS)
    machine = _machine(vram=vram, ram=ram, disk=500)
    best = maximum_for_machine(presets, machine)
    presets.validate_params(best)

    for key, value in expected.items():
        assert best[key] == value, f"Lệch {key} trên máy VRAM {vram} / RAM {ram}: {best[key]} != {value}"

    statuses = {item.resource: item.status for item in evaluate(presets, best, machine).resources}
    assert set(statuses.values()) <= {"ok"}, statuses


def test_maximum_for_machine_decoupled_properties() -> None:
    presets, _ = load_presets(PRESETS)

    # Cùng RAM 16, VRAM tăng dần (4 -> 6 -> 8 -> 24):
    # Nhóm SFM bằng nhau ở mọi máy; brush.max_splats và brush.max_resolution không giảm
    results_16 = [maximum_for_machine(presets, _machine(vram=v, ram=16, disk=500)) for v in (4, 6, 8, 24)]
    base_sfm = {k: results_16[0][k] for k in SFM_KEYS}
    for res in results_16[1:]:
        sfm = {k: res[k] for k in SFM_KEYS}
        assert sfm == base_sfm
    for prev, nxt in zip(results_16[:-1], results_16[1:], strict=True):
        assert float(nxt["brush.max_splats"]) >= float(prev["brush.max_splats"])
        assert float(nxt["brush.max_resolution"]) >= float(prev["brush.max_resolution"])

    # Cùng VRAM 24, RAM 8 so với 16:
    # Nhóm SPLAT bằng nhau; nhóm SFM của máy 8 GB thấp hơn
    m_16 = maximum_for_machine(presets, _machine(vram=24, ram=16, disk=500))
    m_8 = maximum_for_machine(presets, _machine(vram=24, ram=8, disk=500))
    splat_16 = {k: m_16[k] for k in SPLAT_KEYS}
    splat_8 = {k: m_8[k] for k in SPLAT_KEYS}
    assert splat_16 == splat_8
    assert int(m_8["sampling.max_frames"]) < int(m_16["sampling.max_frames"])
    assert int(m_8["colmap.max_image_size"]) < int(m_16["colmap.max_image_size"])
    assert int(m_8["colmap.max_num_features"]) < int(m_16["colmap.max_num_features"])


def test_capability_record_and_latest_ignore_stale_workers(tmp_path: Path) -> None:
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    record(database, _machine().model_copy(update={"worker_id": "old", "measured_at": NOW - timedelta(hours=1)}))
    assert latest(database, now=NOW) is None
    record(database, _machine())
    record(database, _machine(vram=48))
    current = latest(database, now=NOW + timedelta(minutes=1))
    assert current is not None and current.vram_total_gb == 48


def test_resource_model_calibrated_against_real_measurements() -> None:
    presets, _ = load_presets(PRESETS)
    model = presets.resource_model
    min_params = preset_values(presets, "minimum_quality")
    max_params = preset_values(presets, "maximum")

    # Điểm đo RAM cố định từ r2s_resource_usage (AUD-26.S1)
    # job-6bc02e5d: 50 frame (tối thiểu) -> peak RAM đo 1.04 GB
    est_50 = estimate_gb(model, {**min_params, "sampling.max_frames": 50})
    assert est_50["ram"] >= 1.04

    # job-a713242a: 149 frame (tối thiểu) -> peak RAM đo 1.53 GB
    est_149 = estimate_gb(model, {**min_params, "sampling.max_frames": 149})
    assert est_149["ram"] >= 1.53

    # job-9b9aa3da: 174 frame (tối thiểu) -> peak RAM đo 1.46 GB
    est_174 = estimate_gb(model, {**min_params, "sampling.max_frames": 174})
    assert est_174["ram"] >= 1.46

    # job-ed9cf773: 546 frame (tối đa) -> peak RAM đo 4.20 GB (lượt lỗi / tải đỉnh)
    est_546 = estimate_gb(model, {**max_params, "sampling.max_frames": 546})
    assert est_546["ram"] >= 4.20

    # VRAM preset tối thiểu >= 2.63 GB (job-9b9aa3da/job-a713242a đo 2.63 GB)
    est_min = estimate_gb(model, min_params)
    assert est_min["vram"] >= 2.63

    # Chặn trên: RAM preset tối đa nguyên bản (1200 frame) < 12 GB (không quay lại lỗi 87.6 GB)
    est_max = estimate_gb(model, max_params)
    assert est_max["ram"] < 12.0


def test_evaluate_without_observations_preserves_estimated_result() -> None:
    presets, _ = load_presets(PRESETS)
    params = preset_values(presets, "minimum_quality")
    machine = _machine(vram=4, ram=8, disk=100)

    # evaluate(..., observed=None) cho kết quả bằng đúng kết quả trước sprint (so cả object)
    eval_default = evaluate(presets, params, machine)
    eval_none = evaluate(presets, params, machine, observed=None)
    assert eval_none == eval_default


def test_evaluate_uses_observed_budget_for_vram_and_ram() -> None:
    presets, _ = load_presets(PRESETS)
    params = preset_values(presets, "minimum_quality")
    machine = _machine(vram=4, ram=8, disk=100)

    # evaluate(..., observed={"vram": 3.42, "ram": 5.19}) trên máy 4 GB VRAM:
    # tài nguyên VRAM ở trạng thái warn (3.42 / 4 = 0.855), không blocking
    eval_observed = evaluate(presets, params, machine, observed={"vram": 3.42, "ram": 5.19})
    assert not eval_observed.blocking
    vram_est = next(r for r in eval_observed.resources if r.resource == "vram")
    ram_est = next(r for r in eval_observed.resources if r.resource == "ram")
    assert vram_est.status == "warn"
    assert vram_est.required_gb == 3.42
    assert "Đã đo ở lượt chạy trước 3.4 GB" in vram_est.message
    assert ram_est.required_gb == 5.19
    assert "Đã đo ở lượt chạy trước 5.2 GB" in ram_est.message


@pytest.mark.parametrize("colmap_use_gpu", [False, True])
def test_integration_evaluate_and_admission_agree_on_observed_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, colmap_use_gpu: bool
) -> None:
    """Cùng DB có lịch sử, API evaluate và ResourceAdmission._demand cho cùng required RAM/VRAM."""
    from src.api.studio import deps
    from src.api.studio.processing import EvaluateRequest, evaluate_processing
    from src.config import Settings
    from src.services.orchestration.jobs.admission import ResourceAdmission, job_drivers
    from src.services.orchestration.processing.observed import resource_observation_params
    from src.services.orchestration.processing.telemetry import ResourceUsage
    from src.services.orchestration.projects.models import JobCreateInput
    from tests.test_orchestration.test_prepared_queue import _attach_frames, _frame_stage, _registry

    registry = _registry(tmp_path / "runtime")
    presets, checksum = load_presets(PRESETS)
    min_params = preset_values(presets, "minimum_quality")
    config = build_job_config(presets, checksum, min_params, None, colmap_use_gpu=colmap_use_gpu)
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"), config)
    job = _attach_frames(registry, job, _frame_stage(job.job_id))

    # Ghi log đo đạc cho preview và cả hai công cụ của phase finalize.
    num_p = resource_observation_params(min_params, colmap_use_gpu=colmap_use_gpu)
    db = registry.persistence.database
    now = datetime.now(UTC)

    def _make_usage(tool: str, vram: float, ram: float) -> ResourceUsage:
        return ResourceUsage(
            job_id="job-hist",
            attempt_id="att-hist",
            tool=tool,
            config_checksum=job.config_checksum,
            runtime_manifest_checksum=job.runtime_manifest_checksum,
            params=num_p,
            gpu_name="NVIDIA GeForce RTX 4090",
            shared_gpu=False,
            started_at=now,
            completed_at=now,
            outcome="completed",
            exit_code=0,
            duration_seconds=10.0,
            sample_count=1,
            ram_sample_count=1,
            vram_sample_count=1,
            gpu_sample_count=1,
            scratch_sample_count=1,
            peak_ram_gb=ram,
            peak_vram_gb=vram,
            headroom_before={},
        )

    usages = [
        _make_usage("preview", 3.5, 4.0),
        _make_usage("finalize", 2.0, 3.0),
        _make_usage("scene_extract", 3.0, 5.5),
    ]
    with db.transaction(write=True) as tx:
        for idx, u in enumerate(usages):
            tx.execute(
                "INSERT INTO r2s_resource_usage(usage_id,job_id,recorded_at,payload) VALUES (?,?,?,?)",
                (f"u-{idx}", u.job_id, now.isoformat(), u.model_dump_json()),
            )

    record(
        db,
        MachineCapability(
            worker_id="worker-1",
            measured_at=now,
            gpu_name="NVIDIA GeForce RTX 4090",
            vram_total_gb=24.0,
            cpu_count=16,
            ram_total_gb=32.0,
            disk_free_gb=500.0,
        ),
    )

    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'runtime' / 'runtime.db'}",
        product_processing_config=PRESETS,
        product_runtime_manifest=PRESETS.parents[2] / "fixtures/mock_job/runtime_manifest.json",
        product_worker_root=tmp_path / "workers",
        product_colmap_use_gpu=colmap_use_gpu,
    )
    monkeypatch.setattr(deps, "settings", lambda: settings)
    monkeypatch.setattr(deps, "registry", lambda: registry)
    assert job_drivers(registry, settings, job) == num_p

    eval_res = evaluate_processing(EvaluateRequest(params=min_params))
    vram_api = next(r for r in eval_res.resources if r.resource == "vram").required_gb
    ram_api = next(r for r in eval_res.resources if r.resource == "ram").required_gb

    gate = ResourceAdmission(registry, settings)
    demand_preview = gate._demand(job, "preview", "NVIDIA GeForce RTX 4090")
    demand_finalize = gate._demand(job, "finalize", "NVIDIA GeForce RTX 4090")
    assert demand_preview is not None and demand_preview.measured
    assert demand_finalize is not None and demand_finalize.measured

    max_demand_vram = max(demand_preview.required_gb["vram"], demand_finalize.required_gb["vram"])
    max_demand_ram = max(demand_preview.required_gb["ram"], demand_finalize.required_gb["ram"])

    assert vram_api == max_demand_vram == 3.5
    assert ram_api == max_demand_ram == 5.5


def test_build_job_config_colmap_use_gpu() -> None:
    presets, checksum = load_presets(PRESETS)
    params = preset_values(presets, "minimum_quality")
    cfg_default = build_job_config(presets, checksum, params, _machine())
    assert cfg_default.colmap["use_gpu"] is False

    cfg_gpu = build_job_config(presets, checksum, params, _machine(), colmap_use_gpu=True)
    assert cfg_gpu.colmap["use_gpu"] is True

    # Hai kết quả có checksum cấu hình khác nhau
    assert config_bytes(cfg_default) != config_bytes(cfg_gpu)
    # num_threads không đổi giữa hai trường hợp
    assert cfg_default.colmap["num_threads"] == cfg_gpu.colmap["num_threads"]


def test_calibration_script_imports_and_parses_arguments() -> None:
    """Script đối chiếu phải nạp được: đổi tên hàm trong `observed.py` từng làm nó hỏng mà không test nào báo."""
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[2] / "scripts/resources/calibrate_resource_model.py"
    done = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def test_anonymize_is_recorded_only_when_chosen() -> None:
    """Job không chọn che giữ nguyên bytes cấu hình cũ; job chọn che có cấu hình (và checksum) khác."""
    import json

    presets, checksum = load_presets(PRESETS)
    params = preset_values(presets, "minimum_quality")
    plain = build_job_config(presets, checksum, params, _machine(cpu=8))
    chosen = build_job_config(presets, checksum, params, _machine(cpu=8), anonymize=True)

    assert "anonymize" not in json.loads(config_bytes(plain))
    assert json.loads(config_bytes(chosen))["anonymize"] is True
    assert config_bytes(plain) != config_bytes(chosen)
    assert type(chosen).model_validate_json(config_bytes(plain)).anonymize is False
    assert type(chosen).model_validate_json(config_bytes(chosen)).anonymize is True


def test_every_preset_seals_shell_geometry_review_and_multiview() -> None:
    from src.services.orchestration.scene.objectify import SceneObjectifyConfig

    presets, checksum = load_presets(PRESETS)
    for name in presets.presets:
        scene = build_job_config(presets, checksum, preset_values(presets, name), None).scene
        assert (scene["geometry_method"], scene["geometry_review"], scene["refinement"]) == (
            "shell",
            "required",
            "multiview_v1",
        ), name
    # Jobs sealed before these presets carry none of these keys and keep the legacy behaviour.
    defaults = SceneObjectifyConfig()
    assert (defaults.geometry_method, defaults.geometry_review, defaults.refinement) == ("legacy", "legacy", "legacy")
