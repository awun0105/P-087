"""Bản xem nhanh của SOG môi trường (T-068): ≤500 nghìn splat, màu bậc 0; nhỏ ~4–5 lần và quay mượt hơn trên máy yếu.

Tạo nền một lần cho mỗi SOG (theo checksum) bằng splat-transform trên CPU: giảm splat mất cỡ một phút cho scene ~2 triệu
splat, nên lần mở đầu vẫn xem bản đầy đủ. SOG ≤600 nghìn splat không cần bản nhẹ. Đệm dẫn xuất, xoá lúc nào cũng được;
kiểm quyền do route làm trước khi gọi.
"""

import json
import logging
import os
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from threading import Lock, Thread
from typing import Literal

logger = logging.getLogger(__name__)

QUICK_SPLATS = 500_000
MIN_SOURCE_SPLATS = 600_000
_TIMEOUT_SECONDS = 900

QuickState = Literal["ready", "building", "unavailable"]

_lock = Lock()
_building: set[str] = set()
#: Một việc tạo bản nhẹ một lúc cho cả tiến trình API (mỗi việc dùng nhiều CPU).
_queue_lock = Lock()


class QuickSogError(RuntimeError):
    """splat-transform không tạo được bản xem nhanh."""


def _paths(root: Path, checksum: str) -> tuple[Path, Path]:
    key = checksum.removeprefix("sha256:")
    return root / f"{key}.quick.sog", root / f"{key}.unavailable"


def quick_etag(checksum: str) -> str:
    return f'"qsog-{checksum.removeprefix("sha256:")[:40]}"'


def ready_path(root: Path, checksum: str) -> Path | None:
    path, _ = _paths(root, checksum)
    return path if path.is_file() else None


def splat_count(sog: Path) -> int:
    with zipfile.ZipFile(sog) as bundle:
        return int(json.loads(bundle.read("meta.json"))["count"])


def _run(cli: Path, *arguments: str) -> None:
    command = ("nice", "-n", "10", "node", str(cli), "-q", "-w", "-g", "cpu", *arguments)
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as error:
        raise QuickSogError(type(error).__name__) from error


def _convert(cli: Path, source: Path, output: Path, scratch: Path) -> None:
    # splat-transform 3.6.6: `--decimate` phải là bước cuối và ra PLY, nên làm hai lần gọi.
    decimated = scratch / "decimated.ply"
    _run(cli, str(source), "-H", "0", str(decimated), "-d", str(QUICK_SPLATS))
    _run(cli, str(decimated), str(output))
    if not output.is_file() or output.stat().st_size == 0:
        raise QuickSogError("empty output")


def _spawn(work: Callable[[], None]) -> None:
    Thread(target=work, name="quick-sog", daemon=True).start()


def ensure(root: Path, checksum: str, source: Callable[[], Path], cli: Path | None) -> QuickState:
    """Trạng thái bản nhẹ; chưa có thì bắt đầu tạo nền (một lần cho mỗi checksum)."""
    path, marker = _paths(root, checksum)
    if path.is_file():
        return "ready"
    if marker.is_file() or cli is None:
        return "unavailable"
    key = path.name
    with _lock:
        if key in _building:
            return "building"
        _building.add(key)

    def work() -> None:
        try:
            with _queue_lock:
                _build(root, path, marker, source, cli)
        finally:
            with _lock:
                _building.discard(key)

    _spawn(work)
    if path.is_file():
        return "ready"
    return "unavailable" if marker.is_file() else "building"


def _build(root: Path, path: Path, marker: Path, source: Callable[[], Path], cli: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    try:
        sog = source()
        if splat_count(sog) <= MIN_SOURCE_SPLATS:
            marker.write_text("small", encoding="utf-8")
            return
        with tempfile.TemporaryDirectory(dir=root) as scratch:
            output = Path(scratch) / "quick.sog"
            _convert(cli, sog, output, Path(scratch))
            os.replace(output, path)
    except (QuickSogError, OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        logger.warning("Không tạo được bản xem nhanh cause=%s", type(error).__name__)
        try:
            marker.write_text(type(error).__name__, encoding="utf-8")
        except OSError:
            pass
    except Exception:  # noqa: BLE001 - việc nền không được làm sập tiến trình API; lần sau thử lại
        logger.exception("Lỗi bất ngờ khi tạo bản xem nhanh")
