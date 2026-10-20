"""Ảnh frame thu nhỏ (T-066): JPEG dẫn xuất từ frame gốc, đệm theo (checksum, cỡ rộng) trong bộ nhớ và trên đĩa.

Không phải artifact của pipeline: xoá thư mục đệm lúc nào cũng được, lần sau tạo lại. Kiểm quyền do route làm trước khi gọi.
"""

import io
import logging
import os
import tempfile
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from threading import Lock

from PIL import Image

logger = logging.getLogger(__name__)

ALLOWED_WIDTHS = frozenset({160, 320, 640})
_JPEG_QUALITY = 80
_MEMORY_ENTRIES = 256

_memory: OrderedDict[str, bytes] = OrderedDict()
_lock = Lock()
_key_locks: dict[str, Lock] = {}


def clear_memory() -> None:
    """Chỉ cho test: quên bản trong bộ nhớ (đệm đĩa giữ nguyên)."""
    with _lock:
        _memory.clear()


def thumbnail_etag(checksum: str, width: int) -> str:
    return f'"thumb-{checksum.removeprefix("sha256:")[:40]}-{width}"'


def _render_jpeg(source: Path, width: int) -> bytes:
    with Image.open(source) as image:
        image.draft("RGB", (width, width))  # JPEG gốc: giải mã thẳng ở cỡ nhỏ, đỡ RAM/CPU.
        rgb = image.convert("RGB")
        height = max(1, round(rgb.height * width / rgb.width))
        small = rgb.resize((width, height), Image.Resampling.LANCZOS) if rgb.width > width else rgb
        buffer = io.BytesIO()
        small.save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        return buffer.getvalue()


def get_thumbnail(root: Path | None, checksum: str, width: int, source: Callable[[], Path]) -> bytes:
    """JPEG thu nhỏ của frame có `checksum`; `source()` chỉ được gọi khi chưa có trong đệm."""
    if width not in ALLOWED_WIDTHS:
        raise ValueError(f"width must be one of {sorted(ALLOWED_WIDTHS)}")
    key = f"{checksum.removeprefix('sha256:')}-{width}"
    with _lock:
        found = _memory.get(key)
        if found is not None:
            _memory.move_to_end(key)
            return found
        key_lock = _key_locks.setdefault(key, Lock())
    with key_lock:
        with _lock:
            found = _memory.get(key)
        path = root / f"{key}.jpg" if root is not None else None
        if found is None and path is not None:
            try:
                found = path.read_bytes()
            except OSError:
                found = None
        if found is None:
            found = _render_jpeg(source(), width)
            if path is not None:
                _write(path, found)
        with _lock:
            _memory[key] = found
            _memory.move_to_end(key)
            while len(_memory) > _MEMORY_ENTRIES:
                _memory.popitem(last=False)
    with _lock:
        _key_locks.pop(key, None)
    return found


def _write(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            handle.write(data)
        os.replace(handle.name, path)
    except OSError as error:
        logger.warning("Không ghi được đệm ảnh thu nhỏ cause=%s", type(error).__name__)
