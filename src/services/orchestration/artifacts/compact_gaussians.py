"""Gaussian của vật dạng PLY nén của PlayCanvas (T-067): nhỏ ~4 lần so với PLY gốc, tạo bằng splat-transform trên CPU.

Bản nén là đệm dẫn xuất theo checksum PLY gốc (không phải artifact, không đổi SceneIR); xoá thư mục đệm lúc nào cũng được.
Kiểm quyền do route làm trước khi gọi. Không có runtime hoặc chuyển lỗi thì route trả về PLY gốc.
"""

import logging
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from threading import BoundedSemaphore, Lock

from src.runtime_env import runtime_env

logger = logging.getLogger(__name__)

#: Chuyển đồng thời tối đa: mỗi lần ~0,5 s CPU cho 6 MB; giữ API còn CPU cho request khác.
_CONVERSIONS = BoundedSemaphore(2)
_TIMEOUT_SECONDS = 120
_lock = Lock()
_key_locks: dict[str, Lock] = {}


class CompactConversionError(RuntimeError):
    """splat-transform không tạo được PLY nén."""


def compact_cli() -> Path | None:
    """CLI splat-transform của deployment (`R2S_VOXEL_CLI`, image API cũ đặt tên cũ — `runtime_env` đọc cả hai); None nếu không có."""
    value = runtime_env(os.environ, "R2S_VOXEL_CLI")
    return Path(value) if value and Path(value).is_file() else None


def compact_etag(checksum: str) -> str:
    return f'"cply-{checksum.removeprefix("sha256:")[:40]}"'


def _convert(cli: Path, source: Path, output: Path) -> None:
    # `-g cpu`: định dạng PLY nén không cần GPU; tên đích `.compressed.ply` chọn bộ ghi PLY nén.
    try:
        subprocess.run(
            ("node", str(cli), "-w", "-g", "cpu", str(source), str(output)),
            check=True,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CompactConversionError(type(error).__name__) from error
    if not output.is_file() or output.stat().st_size == 0:
        raise CompactConversionError("empty output")


def get_compact(root: Path, checksum: str, source: Callable[[], Path], cli: Path) -> Path:
    """Đường dẫn PLY nén trong đệm; `source()` chỉ được gọi khi chưa có. Ném `CompactConversionError` khi chuyển lỗi."""
    key = checksum.removeprefix("sha256:")
    target = root / f"{key}.compressed.ply"
    if target.is_file():
        return target
    with _lock:
        key_lock = _key_locks.setdefault(key, Lock())
    try:
        with key_lock:
            if target.is_file():
                return target
            root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=root) as scratch, _CONVERSIONS:
                output = Path(scratch) / "object.compressed.ply"
                _convert(cli, source(), output)
                os.replace(output, target)
            return target
    finally:
        with _lock:
            _key_locks.pop(key, None)
