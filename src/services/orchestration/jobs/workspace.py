"""Dọn scratch của attempt đã hoàn tất; không chạm artifact, resume hoặc log.

Caller chịu trách nhiệm verify output, commit job và dừng mọi consumer trước khi
gọi. Module này không suy ra quyền xóa từ tuổi thư mục hoặc trạng thái job.
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_ATTEMPT_NAME = re.compile(r"(?:attempt|finalize)-[0-9a-f]{32}")
_DIAGNOSTIC_SUFFIXES = {".log", ".json", ".jsonl", ".txt", ".yaml", ".yml", ".out", ".err"}


@dataclass(frozen=True)
class CleanupResult:
    """Số file/byte đã dọn và số lỗi; không chứa private filesystem paths."""

    files_removed: int = 0
    bytes_removed: int = 0
    errors: int = 0


def _validate_workspace(workspace: Path, worker_root: Path, artifact_root: Path) -> Path:
    """Chỉ nhận đúng namespace attempt, không đi qua symlink hoặc overlap kho artifact."""
    root = worker_root.expanduser().absolute()
    candidate = workspace.expanduser().absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("Workspace nằm ngoài worker root") from error
    if len(relative.parts) != 2 or not _ATTEMPT_NAME.fullmatch(relative.parts[-1]):
        raise ValueError("Workspace không phải namespace attempt hợp lệ")
    current = root
    for part in ("", *relative.parts):
        current = current / part
        if current.is_symlink():
            raise ValueError("Workspace đi qua symlink")
    resolved, artifacts = candidate.resolve(), artifact_root.expanduser().resolve()
    if resolved.is_relative_to(artifacts) or artifacts.is_relative_to(resolved):
        raise ValueError("Workspace overlap artifact root")
    return candidate


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
            if path.is_symlink() or path.suffix.lower() in _DIAGNOSTIC_SUFFIXES:
                continue
            try:
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
