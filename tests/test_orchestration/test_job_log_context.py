"""Tests for per-job log context and worker line formatting."""

import logging
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier

from src.services.orchestration.jobs.log_context import (
    WORKER_LOG_FORMAT,
    JobLogContextFilter,
    configure_worker_logging,
    job_log_context,
)


def _context_fields() -> tuple[str, str]:
    record = logging.LogRecord("test.worker", logging.INFO, __file__, 1, "sample", (), None)
    JobLogContextFilter().filter(record)
    return record.job_id, record.attempt_id


def test_log_context_sets_and_restores_job_and_attempt_ids() -> None:
    assert _context_fields() == ("-", "-")

    with job_log_context("job-17", "2"):
        assert _context_fields() == ("job-17", "2")
        with job_log_context("job-18", "1"):
            assert _context_fields() == ("job-18", "1")
        assert _context_fields() == ("job-17", "2")

    assert _context_fields() == ("-", "-")


def test_job_contexts_are_isolated_between_threads() -> None:
    barrier = Barrier(2)

    def capture(job: str, attempt: str) -> tuple[str, str]:
        with job_log_context(job, attempt):
            barrier.wait(timeout=5)
            return _context_fields()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(capture, "job-a", "1")
        second = pool.submit(capture, "job-b", "4")
        assert first.result(timeout=5) == ("job-a", "1")
        assert second.result(timeout=5) == ("job-b", "4")


def test_worker_logging_formats_context_and_idle_records() -> None:
    root = logging.getLogger()
    previous_handlers = root.handlers[:]
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    root.handlers = [handler]
    worker_logger = logging.getLogger("test.worker.context")
    previous_level = worker_logger.level
    previous_propagate = worker_logger.propagate
    worker_logger.setLevel(logging.INFO)
    worker_logger.propagate = True

    try:
        configure_worker_logging()
        assert handler.formatter is not None
        assert handler.formatter._fmt == WORKER_LOG_FORMAT

        with job_log_context("job-42", "3"):
            worker_logger.info("stage completed")
        worker_logger.info("queue idle")
    finally:
        root.handlers = previous_handlers
        worker_logger.setLevel(previous_level)
        worker_logger.propagate = previous_propagate

    job_line, idle_line = stream.getvalue().splitlines()
    assert "job=job-42 attempt=3" in job_line
    assert job_line.endswith("test.worker.context: stage completed")
    assert "job=- attempt=-" in idle_line
    assert idle_line.endswith("test.worker.context: queue idle")
