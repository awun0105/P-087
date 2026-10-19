"""T-043 bước 4: thời gian kỳ vọng theo khối lượng scene, từ các lượt đo cùng GPU (hàm thuần)."""

from datetime import UTC, datetime

from src.services.orchestration.processing.expected_duration import (
    FLOOR_SECONDS,
    MIN_SAMPLES,
    Estimate,
    deadline_seconds,
    expected_seconds,
)
from src.services.orchestration.processing.telemetry import ResourceUsage

NOW = datetime(2026, 10, 17, tzinfo=UTC)
ITERS = "brush.total_train_iters"


def _usage(seconds: float, iters: float, **changes: object) -> ResourceUsage:
    fields: dict[str, object] = {
        "job_id": "job-a",
        "attempt_id": "attempt-a",
        "tool": "preview",
        "config_checksum": "c",
        "runtime_manifest_checksum": "runtime-1",
        "params": {ITERS: iters},
        "gpu_name": "NVIDIA A40",
        "shared_gpu": False,
        "started_at": NOW,
        "completed_at": NOW,
        "outcome": "completed",
        "exit_code": 0,
        "duration_seconds": seconds,
        "sample_count": 1,
        "ram_sample_count": 1,
        "vram_sample_count": 1,
        "gpu_sample_count": 1,
        "scratch_sample_count": 1,
        "peak_ram_gb": 2.0,
        "peak_vram_gb": 1.0,
        "headroom_before": {},
    }
    return ResourceUsage(**{**fields, **changes})


def _estimate(usages: list[ResourceUsage], iters: float = 1000, **changes: object) -> Estimate | None:
    arguments: dict[str, object] = {
        "tool": "preview",
        "params": {ITERS: iters},
        "gpu_name": "NVIDIA A40",
        "runtime_manifest_checksum": "runtime-1",
        "usages": usages,
    }
    return expected_seconds(**{**arguments, **changes})  # type: ignore[arg-type]


def test_median_rate_scales_with_the_job_work_units() -> None:
    usages = [_usage(100, 1000), _usage(200, 1000), _usage(300, 1000)]

    estimate = _estimate(usages, iters=2000)

    assert estimate is not None
    assert estimate.samples == MIN_SAMPLES
    assert estimate.seconds == 400  # trung vị 0,2 s/vòng × 2000 vòng
    assert estimate.scope == "cùng runtime"


def test_doubling_the_work_doubles_the_estimate() -> None:
    usages = [_usage(100, 1000), _usage(200, 1000), _usage(300, 1000)]

    small = _estimate(usages, iters=1000)
    large = _estimate(usages, iters=2000)

    assert small is not None and large is not None
    assert large.seconds == 2 * small.seconds


def test_too_few_samples_give_no_estimate() -> None:
    assert _estimate([_usage(100, 1000), _usage(200, 1000)]) is None


def test_other_gpus_and_failed_runs_are_ignored() -> None:
    other_gpu = [_usage(100, 1000, gpu_name="NVIDIA H100") for _ in range(5)]
    failed = [_usage(100, 1000, outcome="failed") for _ in range(5)]

    assert _estimate(other_gpu + failed) is None


def test_same_runtime_is_preferred_when_it_has_enough_samples() -> None:
    same = [_usage(100, 1000), _usage(100, 1000), _usage(100, 1000)]
    other = [_usage(900, 1000, runtime_manifest_checksum="runtime-2") for _ in range(5)]

    estimate = _estimate(same + other)

    assert estimate is not None
    assert estimate.scope == "cùng runtime"
    assert estimate.seconds == 100


def test_other_runtime_on_the_same_gpu_is_used_when_the_current_runtime_is_unmeasured() -> None:
    other = [_usage(300, 1000, runtime_manifest_checksum="runtime-2") for _ in range(3)]

    estimate = _estimate(other)

    assert estimate is not None
    assert estimate.scope == "cùng GPU"
    assert estimate.seconds == 300


def test_unknown_tool_or_missing_work_units_give_no_estimate() -> None:
    usages = [_usage(100, 1000) for _ in range(3)]

    assert _estimate(usages, tool="unknown_tool") is None
    assert _estimate(usages, params={}) is None
    assert _estimate(usages, gpu_name=None) is None


def test_deadline_is_three_times_the_estimate_with_a_floor_and_the_fixed_cap() -> None:
    fast = Estimate("preview", 50, 0.05, 1000, 3, "NVIDIA A40", "cùng runtime")
    slow = Estimate("preview", 1000, 1.0, 1000, 3, "NVIDIA A40", "cùng runtime")

    assert deadline_seconds(fast, fixed_limit=21600) == FLOOR_SECONDS
    assert deadline_seconds(slow, fixed_limit=21600) == 3000
    assert deadline_seconds(slow, fixed_limit=1800) == 1800
