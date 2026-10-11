"""Retry policy keeps known input errors terminal and transient failures actionable."""

import pytest

from src.models.contracts.manifests import ExecutionError, StageId
from src.models.contracts.retryability import classify_retryability, is_execution_error_retryable


@pytest.mark.parametrize(
    "error_code",
    [
        "COLMAP_REGISTRATION_LOW",
        "COLMAP_GUIDANCE_INVALID",
        "COLMAP_PROCESS_FAILED",
        "FRAME_IO_FAILED",
        "FRAME_QUALITY_MISMATCH",
        "LIDAR_PACKAGE_INVALID",
        "VISUAL_PROCESS_FAILED",
    ],
)
def test_input_and_contract_errors_are_not_retryable(error_code: str) -> None:
    assert classify_retryability(error_code, {"exception_type": "OSError"}) is False


@pytest.mark.parametrize("error_code", ["COLMAP_TIMEOUT", "VISUAL_OUT_OF_MEMORY", "INTERRUPTED_SHUTDOWN"])
def test_known_recoverable_runtime_errors_are_retryable(error_code: str) -> None:
    assert classify_retryability(error_code) is True


@pytest.mark.parametrize("exception_type", ["TimeoutExpired", "OutOfMemoryError"])
def test_boundary_failures_require_a_transient_exception(exception_type: str) -> None:
    assert classify_retryability("REC_FINALIZE_FAILED", {"exception_type": exception_type}) is True
    assert classify_retryability("REC_FINALIZE_FAILED", {"exception_type": "ValueError"}) is False
    assert classify_retryability("REC_FINALIZE_FAILED", None) is False


def test_dependency_and_io_failures_require_a_transient_exception() -> None:
    assert classify_retryability("FRAME_IO_FAILED", {"exception_type": "ConnectionResetError"}) is True
    assert classify_retryability("COLMAP_DEPENDENCY_FAILED", {"exception_type": "TimeoutError"}) is True
    assert classify_retryability("VISUAL_DEPENDENCY_FAILED", {"exception_type": "ValueError"}) is False
    assert classify_retryability("FRAME_IO_FAILED", {"exception_type": "FileNotFoundError"}) is False
    assert classify_retryability("REC_FINALIZE_FAILED", {"exception_type": "OSError"}) is False


def test_execution_error_retry_flag_cannot_override_error_code_policy() -> None:
    error = ExecutionError(
        error_code="COLMAP_REGISTRATION_LOW",
        stage_id=StageId.CAMERA_POSE,
        human_message="too few registered frames",
        retryable=True,
    )
    assert is_execution_error_retryable(error) is False
