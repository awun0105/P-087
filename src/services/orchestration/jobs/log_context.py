"""Add job and attempt identifiers to worker log records."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

job_id: ContextVar[str] = ContextVar("job_id", default="-")
attempt_id: ContextVar[str] = ContextVar("attempt_id", default="-")

WORKER_LOG_FORMAT = "%(asctime)s %(levelname)s job=%(job_id)s attempt=%(attempt_id)s %(name)s: %(message)s"


class JobLogContextFilter(logging.Filter):
    """Attach the current job context to each record handled by the worker."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = job_id.get()
        record.attempt_id = attempt_id.get()
        return True


@contextmanager
def job_log_context(job_id_value: str, attempt_id_value: str) -> Iterator[None]:
    """Set identifiers for this execution context and reliably restore its parent."""
    job_token = job_id.set(job_id_value)
    attempt_token = attempt_id.set(attempt_id_value)
    try:
        yield
    finally:
        attempt_id.reset(attempt_token)
        job_id.reset(job_token)


def configure_worker_logging() -> None:
    """Configure the worker format and add the context filter to root handlers."""
    logging.basicConfig(level=logging.INFO, format=WORKER_LOG_FORMAT)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(item, JobLogContextFilter) for item in handler.filters):
            handler.addFilter(JobLogContextFilter())
        handler.setFormatter(logging.Formatter(WORKER_LOG_FORMAT))
