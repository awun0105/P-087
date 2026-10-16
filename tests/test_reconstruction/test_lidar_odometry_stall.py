"""T-043 bước 3 (LiDAR odometry): provider không báo tiến độ trong cửa sổ treo thì bị dừng; có tiến độ thì không."""

import time
from pathlib import Path

import pytest

from src.models.contracts.retryability import classify_retryability
from src.services.reconstruction.lidar.odometry import (
    KissIcpProcess,
    LidarOdometryProcessError,
    LidarOdometryProfile,
    LidarOdometryRuntimeSettings,
    LidarOdometryStalledError,
)


def _profile() -> LidarOdometryProfile:
    return LidarOdometryProfile(
        min_range_m=0,
        max_range_m=80,
        voxel_size_m=0.25,
        min_points_per_scan=3,
        max_points_per_scan=100,
    )


def _run(tmp_path: Path, script: str, stall_seconds: float) -> None:
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    fake_python.chmod(0o755)
    settings = LidarOdometryRuntimeSettings(
        python=fake_python,
        work_root=tmp_path / "attempts",
        timeout_seconds=30,
        stall_seconds=stall_seconds,
    )
    KissIcpProcess(settings).run(
        tmp_path / "manifest.json",
        tmp_path / "output.json",
        tmp_path / "provider.log",
        _profile(),
        cancel_event=None,
        lease_is_current=lambda: True,
    )


def test_stall_window_default_and_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    assert LidarOdometryRuntimeSettings().stall_seconds == 300
    monkeypatch.setenv("R2S_LIDAR_ODOMETRY_STALL_SECONDS", "11")
    assert LidarOdometryRuntimeSettings().stall_seconds == 11


def test_silent_provider_is_stopped_as_stalled_and_is_retryable(tmp_path: Path) -> None:
    started = time.monotonic()
    with pytest.raises(LidarOdometryStalledError) as error:
        _run(tmp_path, "echo 'registering scan'\nsleep 60", stall_seconds=1)
    assert time.monotonic() - started < 15
    assert error.value.error_code == "LIDAR_ODOMETRY_STALLED"
    assert "không tiến triển" in str(error.value)
    assert classify_retryability("LIDAR_ODOMETRY_STALLED") is True


def test_provider_that_keeps_reporting_is_not_stopped(tmp_path: Path) -> None:
    """Provider chạy xong (không ghi output) báo lỗi quy trình thường, không báo treo."""
    script = 'for i in 1 2 3 4 5 6 7 8 9 10; do echo "{\\"scan\\": $i}"; sleep 0.2; done'
    with pytest.raises(LidarOdometryProcessError):
        _run(tmp_path, script, stall_seconds=1)
