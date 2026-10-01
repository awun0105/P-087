"""Kho tạm cục bộ trên máy worker để một attempt mới dùng lại việc attempt trước đã làm xong.

Vì sao cần: train 3DGS dài (hàng chục phút tới hàng giờ); máy tắt/worker chết giữa chừng thì attempt đó
`FAILED` và retry là attempt mới, workspace mới. Không có kho này retry chạy lại COLMAP (cho ra hệ toạ độ
SfM **khác**) rồi train lại từ bước 0.

Hai thứ được giữ, đều theo khoá nội dung (frame set + cấu hình + runtime), không theo attempt:

- **Sparse model COLMAP đã hoàn tất** của lần chạy thành công — không giữ database/sparse dở dang, nên vẫn
  đúng quy tắc "không resume database cũ, không biến partial output thành success" của REC-03.
- **Checkpoint Brush** (PLY xuất định kỳ). Chỉ hợp lệ với đúng sparse model đã giữ: checkpoint nằm trong
  hệ toạ độ của lần COLMAP đó, nên ghi sparse model mới là xoá checkpoint cũ.

Kho này là trạng thái vận hành, **không phải artifact**: mọi artifact vẫn được publish trong namespace
của attempt đang chạy; log artifact ghi rõ khi có dùng lại. Mất kho (máy khác, phiên Kaggle mới) thì
pipeline chạy lại từ đầu như trước.
"""

import hashlib
import logging
import re
import shutil
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

_CHECKPOINT = re.compile(r"ckpt_(\d+)\.ply")
CHECKPOINT_NAME = "ckpt_{iter}.ply"
_PLY_TYPE_BYTES = {"float": 4, "float32": 4, "double": 8, "float64": 8, "uchar": 1, "uint8": 1, "int": 4, "uint": 4}
_PLY_TYPE_BYTES.update(
    {"int32": 4, "uint32": 4, "short": 2, "ushort": 2, "int16": 2, "uint16": 2, "char": 1, "int8": 1}
)


def content_key(*parts: str) -> str:
    """Khoá kho từ các định danh nội dung (checksum frame set, checksum cấu hình, identity runtime…)."""
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:32]


def ply_is_complete(path: Path) -> bool:
    """PLY nhị phân có đủ byte theo header không — checkpoint đang ghi dở lúc máy tắt thì bị cắt cụt."""
    try:
        with path.open("rb") as stream:
            head = stream.read(65536)
    except OSError:
        return False
    end = head.find(b"end_header\n")
    if not head.startswith(b"ply") or end < 0:
        return False
    count, row = 0, 0
    for line in head[:end].decode("ascii", "replace").splitlines():
        words = line.split()
        if words[:2] == ["element", "vertex"]:
            count = int(words[2])
        elif words[:1] == ["property"] and len(words) == 3:
            if words[1] not in _PLY_TYPE_BYTES:
                return False
            row += _PLY_TYPE_BYTES[words[1]]
        elif words[:1] == ["element"] and words[1:2] != ["vertex"]:
            return False  # checkpoint Brush chỉ có phần tử vertex; dạng khác thì không dám dùng
    return count > 0 and row > 0 and path.stat().st_size == end + len(b"end_header\n") + count * row


class ResumeCache:
    """Một thư mục cho mỗi job trên máy worker (`<PRODUCT_WORKER_ROOT>/<job_id>/resume`)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # --- COLMAP -----------------------------------------------------------

    def _colmap(self, key: str) -> Path:
        return self.root / f"colmap-{key}"

    def restore_colmap(self, key: str, workspace: Path) -> bool:
        """Chép sparse model đã giữ vào workspace mới; trả False nếu chưa có (nơi gọi chạy COLMAP thật)."""
        source = self._colmap(key)
        if not (source / "sparse").is_dir() or not (source / "process.log").is_file():
            return False
        shutil.copytree(source / "sparse", workspace / "sparse")
        with (workspace / "process.log").open("a") as log:
            log.write(f"REUSED_SPARSE_MODEL key={key}: dùng lại kết quả COLMAP của lần chạy trước; log của lần đó:\n")
            log.write((source / "process.log").read_text())
        logger.info("REC-03 dùng lại sparse model key=%s", key)
        return True

    def store_colmap(self, key: str, workspace: Path) -> None:
        """Giữ sparse model của lần COLMAP vừa thành công; checkpoint Brush của sparse cũ không còn hợp lệ."""
        target = self._colmap(key)
        staging = self.root / f".staging-{uuid4().hex}"
        staging.mkdir(parents=True)
        shutil.copytree(workspace / "sparse", staging / "sparse")
        shutil.copyfile(workspace / "process.log", staging / "process.log")
        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)  # đổi tên sau cùng: không bao giờ có kho dở dang ở đường dẫn thật
        self.clear_checkpoints(key)

    # --- Brush ------------------------------------------------------------

    def checkpoint_dir(self, key: str) -> Path:
        """Nơi Brush xuất checkpoint của khoá này (tạo nếu chưa có)."""
        path = self.root / f"brush-{key}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def latest_checkpoint(self, key: str, below: int) -> tuple[int, Path] | None:
        """Checkpoint nguyên vẹn có số bước lớn nhất và nhỏ hơn `below` (tổng số bước); None nếu không có."""
        found = []
        for path in (self.root / f"brush-{key}").glob("ckpt_*.ply"):
            match = _CHECKPOINT.fullmatch(path.name)
            if match and int(match.group(1)) < below and ply_is_complete(path):
                found.append((int(match.group(1)), path))
        return max(found) if found else None

    def clear_checkpoints(self, key: str) -> None:
        """Xoá checkpoint của khoá (train xong, hoặc sparse model đã đổi)."""
        shutil.rmtree(self.root / f"brush-{key}", ignore_errors=True)


def checkpoint_interval(total_steps: int, target: int) -> int:
    """Số bước giữa hai lần xuất, chia hết `total_steps` để lần xuất cuối rơi đúng bước cuối."""
    for count in range(max(1, round(total_steps / max(1, target))), 0, -1):
        if total_steps % count == 0:
            return total_steps // count
    return total_steps
