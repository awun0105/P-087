"""Retry policy for structured execution errors shared across pipeline boundaries."""

from collections.abc import Mapping

from src.models.contracts.manifests import ExecutionError

# Deterministic input/contract failures are deliberately absent. Unknown codes fail closed.
_RETRYABLE_ERROR_CODES = frozenset(
    {
        "BRUSH_CLI_UNSUPPORTED",
        "BRUSH_VERSION_MISMATCH",
        "COLMAP_CLI_UNSUPPORTED",
        "COLMAP_OUT_OF_MEMORY",
        "COLMAP_TIMEOUT",
        "EXPECTED_DURATION_EXCEEDED",
        "PROCESS_STALLED",
        "COLMAP_UNAVAILABLE",
        "COLMAP_VERSION_UNKNOWN",
        "FFMPEG_UNAVAILABLE",
        "INTERRUPTED_SHUTDOWN",
        "LIDAR_ODOMETRY_OUT_OF_MEMORY",
        "LIDAR_ODOMETRY_RUNTIME_UNAVAILABLE",
        "LIDAR_ODOMETRY_STALLED",
        "LIDAR_ODOMETRY_TIMEOUT",
        "VISUAL_GPU_DEADLOCK",
        "VISUAL_OUT_OF_MEMORY",
        "VISUAL_RUNTIME_UNAVAILABLE",
        "VISUAL_TIMEOUT",
    }
)

# Boundary errors can be retried only when the underlying failure is clearly transient.
_EXCEPTION_CLASSIFIED_ERROR_CODES = frozenset(
    {
        "PREPARED_DISPATCH_FAILED",
        "PREVIEW_RUNNER_FAILED",
        "COLMAP_DEPENDENCY_FAILED",
        "FRAME_IO_FAILED",
        "REC_FINALIZE_DISPATCH_FAILED",
        "REC_FINALIZE_FAILED",
        "RECONSTRUCTION_FAILED",
        "RECONSTRUCTION_PREVIEW_FAILED",
        "VISUAL_DEPENDENCY_FAILED",
    }
)
_TRANSIENT_EXCEPTION_TYPES = frozenset(
    {
        "BrokenPipeError",
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "ConnectionAbortedError",
        "MemoryError",
        "TimeoutError",
        "TimeoutExpired",
        "OutOfMemoryError",
        # Lỗi DB kéo dài (sqlite/psycopg) sau khi đã chịu hết khoảng cho phép: lần chạy mới có thể qua.
        "OperationalError",
        "InterfaceError",
    }
)


#: Exceptions raised in a runner when the worker process itself is being stopped.
_SHUTDOWN_EXCEPTION_TYPES = frozenset({"KeyboardInterrupt", "SystemExit"})


def classify_retryability(error_code: str, details: Mapping[str, object] | None = None) -> bool:
    """Return whether this known error can plausibly recover in a fresh attempt.

    Input/contract and unknown failures are non-retryable by default. A retryable
    runtime or transient error may be retried after its cause is corrected.
    """
    if error_code in _RETRYABLE_ERROR_CODES:
        return True
    if error_code not in _EXCEPTION_CLASSIFIED_ERROR_CODES or details is None:
        return False
    exception_type = details.get("exception_type")
    return isinstance(exception_type, str) and exception_type in _TRANSIENT_EXCEPTION_TYPES


def is_execution_error_retryable(error: ExecutionError) -> bool:
    """Honor the producer flag only when its error type is allowed by policy.

    A runner stopped by a worker shutdown (SIGTERM/Ctrl-C, deploy) is an interruption, not a
    failure of the job, so it is always retryable — including jobs recorded before that rule,
    which carry ``retryable=False``.
    """
    if (
        error.error_code == "PREVIEW_RUNNER_FAILED"
        and error.details is not None
        and error.details.get("exception_type") in _SHUTDOWN_EXCEPTION_TYPES
    ):
        return True
    return error.retryable and classify_retryability(error.error_code, error.details)
