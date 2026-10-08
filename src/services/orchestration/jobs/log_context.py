"""Gắn job_id và attempt_id vào log record của worker qua contextvars (AUD-27.S3)."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_JOB_ID: ContextVar[str] = ContextVar("job_id", default="-")
_ATTEMPT_ID: ContextVar[str] = ContextVar("attempt_id", default="-")

WORKER_LOG_FORMAT = "%(asctime)s %(levelname)s job=%(job_id)s attempt=%(attempt_id)s %(name)s: %(message)s"
JOB_LOG_FORMAT = WORKER_LOG_FORMAT


class JobLogContextFilter(logging.Filter):
    """Logging filter bổ sung job_id và attempt_id từ context hiện tại vào record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = _JOB_ID.get()  # type: ignore[attr-defined]
        record.attempt_id = _ATTEMPT_ID.get()  # type: ignore[attr-defined]
        return True


JobLogFilter = JobLogContextFilter


@contextmanager
def job_log_context(job_id: str | None, attempt_id: str | None) -> Iterator[None]:
    """Context manager thiết lập job_id và attempt_id cho luồng log hiện tại."""
    t_job = _JOB_ID.set(job_id or "-")
    t_att = _ATTEMPT_ID.set(attempt_id or "-")
    try:
        yield
    finally:
        _JOB_ID.reset(t_job)
        _ATTEMPT_ID.reset(t_att)


def configure_worker_logging(level: int = logging.INFO) -> None:
    """Cấu hình logging cho worker CLI và runner."""
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(WORKER_LOG_FORMAT)
    log_filter = JobLogContextFilter()

    if not root.handlers:
        handler = logging.StreamHandler()
        root.addHandler(handler)

    for handler in root.handlers:
        handler.setFormatter(formatter)
        if not any(isinstance(f, JobLogContextFilter) for f in handler.filters):
            handler.addFilter(log_filter)
