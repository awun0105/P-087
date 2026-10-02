"""Dọn scratch của worker; không chạm artifact đã publish hoặc log chẩn đoán.

Ba mức, đều giữ file chẩn đoán:

- `cleanup_attempt_workspace`: attempt vừa commit thành công (caller đã verify output).
- `cleanup_finished_job`: job đã SUCCEEDED — scratch của các attempt cũ và thư mục resume.
- `reclaim_worker_scratch`: đĩa thiếu — scratch của attempt không còn ai dùng ở mọi job.

Quyền xoá attempt của người khác chỉ đến từ bằng chứng nó không còn chạy: lease
(`flock` trên `attempt.lock`, tự nhả khi tiến trình chết) và không tiến trình nào đứng
trong thư mục. Tuổi thư mục hoặc trạng thái job không cấp quyền xoá.
"""

import fcntl
import logging
import os
import re
import shutil
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from src.services.orchestration.processing.procfs import any_process_inside

logger = logging.getLogger(__name__)

_ATTEMPT_NAME = re.compile(r"(?:attempt|finalize)-[0-9a-f]{32}")
#: Log và journal luôn được giữ.
_LOG_SUFFIXES = {".log", ".jsonl"}
#: Request/response/cấu hình nhỏ có ích khi chẩn đoán; file lớn cùng đuôi (model COLMAP dạng
#: text, transforms) là dữ liệu trung gian. Ngưỡng trùng giới hạn response của tool trong runner.
_SMALL_DIAGNOSTIC_SUFFIXES = {".json", ".txt", ".yaml", ".yml", ".out", ".err"}
_SMALL_DIAGNOSTIC_BYTES = 1048576
LEASE_NAME = "attempt.lock"
RESUME_NAME = "resume"


@dataclass(frozen=True)
class CleanupResult:
    """Số file/byte đã dọn và số lỗi; không chứa private filesystem paths."""

    files_removed: int = 0
    bytes_removed: int = 0
    errors: int = 0

    def __add__(self, other: "CleanupResult") -> "CleanupResult":
        return CleanupResult(
            self.files_removed + other.files_removed,
            self.bytes_removed + other.bytes_removed,
            self.errors + other.errors,
        )


def _resolved_root(worker_root: Path) -> Path:
    """Root thật sau khi giải symlink: runner cũng tạo workspace dưới đường dẫn đã giải."""
    return worker_root.expanduser().resolve()


def _validate_workspace(workspace: Path, worker_root: Path, artifact_root: Path) -> Path:
    """Chỉ nhận đúng namespace attempt dưới worker root, không overlap kho artifact.

    Worker root được giải symlink (dữ liệu có thể nằm trên ổ khác qua symlink); hai cấp
    bên dưới nó — thư mục job và thư mục attempt — thì không được là symlink.
    """
    root = _resolved_root(worker_root)
    candidate = workspace.expanduser().absolute()
    for base in (root, worker_root.expanduser().absolute()):
        try:
            relative = candidate.relative_to(base)
            break
        except ValueError:
            continue
    else:
        raise ValueError("Workspace nằm ngoài worker root")
    if len(relative.parts) != 2 or not _ATTEMPT_NAME.fullmatch(relative.parts[-1]):
        raise ValueError("Workspace không phải namespace attempt hợp lệ")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Workspace đi qua symlink")
    artifacts = artifact_root.expanduser().resolve()
    if current.is_relative_to(artifacts) or artifacts.is_relative_to(current):
        raise ValueError("Workspace overlap artifact root")
    return current


def _is_diagnostic(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in _LOG_SUFFIXES:
        return True
    return suffix in _SMALL_DIAGNOSTIC_SUFFIXES and path.stat().st_size <= _SMALL_DIAGNOSTIC_BYTES


def cleanup_attempt_workspace(workspace: Path, *, worker_root: Path, artifact_root: Path) -> CleanupResult:
    """Dọn scratch idempotent, giữ diagnostic files và không follow symlink.

    Path guard lỗi là programming/config error. Lỗi I/O được báo qua result/log;
    caller không được đổi success đã commit thành FAILED vì lỗi cleanup.
    """
    candidate = _validate_workspace(workspace, worker_root, artifact_root)
    if not candidate.exists():
        return CleanupResult()
    removed, size, errors = 0, 0, 0

    def on_error(error: OSError) -> None:
        """Ghi loại lỗi, không đưa private paths vào log."""
        nonlocal errors
        if isinstance(error, FileNotFoundError):
            return
        errors += 1
        logger.warning("Không dọn được scratch cause=%s", type(error).__name__)

    for directory, _, filenames in os.walk(candidate, topdown=False, followlinks=False, onerror=on_error):
        parent = Path(directory)
        for name in filenames:
            path = parent / name
            try:
                if path.is_symlink() or _is_diagnostic(path):
                    continue
                count = path.stat().st_size
                path.unlink()
            except FileNotFoundError:
                continue  # Retry/concurrent cleanup đã xử lý file này.
            except OSError as error:
                on_error(error)
            else:
                removed += 1
                size += count
        try:
            if not any(parent.iterdir()):
                parent.rmdir()
        except FileNotFoundError:
            pass
        except OSError as error:
            on_error(error)
    return CleanupResult(files_removed=removed, bytes_removed=size, errors=errors)


@contextmanager
def attempt_lease(workspace: Path) -> Iterator[None]:
    """Giữ lease của attempt suốt thời gian runner chạy trong workspace.

    `flock` gắn với file đang mở nên tự nhả khi worker thoát hoặc bị kill; không cần
    dọn lease mồ côi. File lease là scratch: cleanup của chính attempt xoá được nó.
    """
    with (workspace / LEASE_NAME).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def attempt_in_use(workspace: Path) -> bool:
    """True khi còn bằng chứng attempt đang chạy, hoặc khi không kiểm được (thiên về giữ lại)."""
    lease = workspace / LEASE_NAME
    if lease.is_file() and not lease.is_symlink():
        try:
            with lease.open("a") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            return True
    inside = any_process_inside(workspace)
    return inside is None or inside


def _job_attempts(job_root: Path) -> list[Path]:
    try:
        return sorted(
            child
            for child in job_root.iterdir()
            if _ATTEMPT_NAME.fullmatch(child.name) and child.is_dir() and not child.is_symlink()
        )
    except OSError:
        return []


def _cleanup_idle_attempts(job_root: Path, worker_root: Path, artifact_root: Path) -> CleanupResult:
    total = CleanupResult()
    for workspace in _job_attempts(job_root):
        if attempt_in_use(workspace):
            continue
        try:
            total += cleanup_attempt_workspace(workspace, worker_root=worker_root, artifact_root=artifact_root)
        except ValueError:
            total += CleanupResult(errors=1)
    return total


def _job_root(job_id: str, worker_root: Path) -> Path | None:
    """Thư mục của job ngay dưới worker root; None khi tên/đường dẫn không an toàn."""
    root = _resolved_root(worker_root)
    job_root = root / job_id
    if Path(job_id).name != job_id or job_root.parent != root or job_root.is_symlink() or not job_root.is_dir():
        return None
    return job_root


def cleanup_finished_job(job_id: str, *, worker_root: Path, artifact_root: Path) -> CleanupResult:
    """Job đã SUCCEEDED: dọn scratch của mọi attempt không còn chạy và bỏ thư mục resume.

    Resume (sparse model COLMAP, checkpoint Brush) chỉ phục vụ retry của bước preview;
    job đã thành công không còn retry nào đọc nó. Caller chịu trách nhiệm chỉ gọi sau
    khi trạng thái SUCCEEDED đã commit.
    """
    job_root = _job_root(job_id, worker_root)
    if job_root is None:
        return CleanupResult()
    total = _cleanup_idle_attempts(job_root, worker_root, artifact_root)
    resume = job_root / RESUME_NAME
    if resume.is_dir() and not resume.is_symlink():
        size = sum(path.stat().st_size for path in resume.rglob("*") if path.is_file() and not path.is_symlink())
        count = sum(1 for path in resume.rglob("*") if path.is_file() and not path.is_symlink())
        failures: list[OSError] = []
        shutil.rmtree(resume, onexc=lambda function, path, error: failures.append(error))
        if failures:
            logger.warning("Không dọn hết resume cause=%s", type(failures[0]).__name__)
            total += CleanupResult(errors=len(failures))
        else:
            total += CleanupResult(files_removed=count, bytes_removed=size)
    return total


def reclaim_worker_scratch(*, worker_root: Path, artifact_root: Path, protected_jobs: Collection[str]) -> CleanupResult:
    """Đĩa thiếu: dọn scratch của attempt không còn ai dùng ở mọi job trên máy này.

    Bỏ qua job trong `protected_jobs` (đang có worker giữ chỗ) và attempt còn lease
    hoặc còn tiến trình đứng trong đó. Không đụng resume: job lỗi/huỷ còn có thể retry
    và resume là thứ cho phép retry không phải chạy lại COLMAP/Brush.
    """
    root = _resolved_root(worker_root)
    total = CleanupResult()
    try:
        jobs = sorted(child for child in root.iterdir() if child.is_dir() and not child.is_symlink())
    except OSError as error:
        logger.warning("Không liệt kê được worker root cause=%s", type(error).__name__)
        return CleanupResult(errors=1)
    for job_root in jobs:
        if job_root.name in protected_jobs:
            continue
        total += _cleanup_idle_attempts(job_root, worker_root, artifact_root)
    return total
