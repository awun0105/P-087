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
import json
import logging
import re
import shutil
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

_CHECKPOINT = re.compile(r"ckpt_(\d+)\.ply")
CHECKPOINT_NAME = "ckpt_{iter}.ply"
_COLMAP_MANIFEST_NAME = "cache-manifest.json"
_COLMAP_MANIFEST_SCHEMA = "1.0"
_BRUSH_CACHE_PREFIX = "brush-v2"
_PLY_TYPE_BYTES = {"float": 4, "float32": 4, "double": 8, "float64": 8, "uchar": 1, "uint8": 1, "int": 4, "uint": 4}
_PLY_TYPE_BYTES.update(
    {"int32": 4, "uint32": 4, "short": 2, "ushort": 2, "int16": 2, "uint16": 2, "char": 1, "int8": 1}
)


def content_key(*parts: str) -> str:
    """Khoá kho từ các định danh nội dung (checksum frame set, checksum cấu hình, identity runtime…)."""
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:32]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def ply_is_complete(path: Path) -> bool:
    """PLY nhị phân có đủ byte theo header không — checkpoint đang ghi dở lúc máy tắt thì bị cắt cụt."""
    try:
        with path.open("rb") as stream:
            head = stream.read(65536)
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
        expected_size = end + len(b"end_header\n") + count * row
        return count > 0 and row > 0 and path.stat().st_size == expected_size
    except (IndexError, OSError, ValueError):
        return False


class ResumeCache:
    """Một thư mục cho mỗi job trên máy worker (`<PRODUCT_WORKER_ROOT>/<job_id>/resume`)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # --- COLMAP -----------------------------------------------------------

    def _colmap(self, key: str) -> Path:
        return self.root / f"colmap-{key}"

    def _brush(self, key: str) -> Path:
        """Namespace mới để checkpoint cũ, chưa có checksum, không bị tin hoặc ghi đè."""
        return self.root / f"{_BRUSH_CACHE_PREFIX}-{key}"

    @staticmethod
    def _colmap_inventory(root: Path) -> dict[str, dict[str, int | str]] | None:
        """Checksummed inventory của log và sparse files; symlink/thiếu file là cache miss."""
        sparse = root / "sparse"
        process_log = root / "process.log"
        if not sparse.is_dir() or sparse.is_symlink() or not process_log.is_file() or process_log.is_symlink():
            return None
        files: dict[str, dict[str, int | str]] = {}
        try:
            candidates = sorted(sparse.rglob("*"))
            if any(path.is_symlink() for path in candidates):
                return None
            for path in candidates:
                if path.is_file():
                    files[path.relative_to(root).as_posix()] = {
                        "checksum": _sha256_file(path),
                        "size_bytes": path.stat().st_size,
                    }
            files["process.log"] = {"checksum": _sha256_file(process_log), "size_bytes": process_log.stat().st_size}
        except OSError:
            return None
        if not any(name.startswith("sparse/") for name in files):
            return None
        return files

    @staticmethod
    def _colmap_manifest_bytes(key: str, files: dict[str, dict[str, int | str]]) -> bytes:
        payload: dict[str, object] = {"schema_version": _COLMAP_MANIFEST_SCHEMA, "cache_key": key, "files": files}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["manifest_checksum"] = "sha256:" + hashlib.sha256(canonical).hexdigest()
        return json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n"

    def _colmap_cache_valid(self, key: str, source: Path) -> bool:
        manifest_path = source / _COLMAP_MANIFEST_NAME
        try:
            if source.is_symlink() or manifest_path.is_symlink() or not manifest_path.is_file():
                return False
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return False
            checksum = payload.pop("manifest_checksum", None)
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if (
                payload.get("schema_version") != _COLMAP_MANIFEST_SCHEMA
                or payload.get("cache_key") != key
                or checksum != "sha256:" + hashlib.sha256(canonical).hexdigest()
            ):
                return False
            expected_files = payload.get("files")
            return isinstance(expected_files, dict) and expected_files == self._colmap_inventory(source)
        except (OSError, TypeError, ValueError):
            return False

    @staticmethod
    def _checkpoint_receipt(path: Path) -> Path:
        return path.with_name(f"{path.name}.integrity.json")

    def _checkpoint_is_attested(self, path: Path) -> bool:
        receipt_path = self._checkpoint_receipt(path)
        try:
            if receipt_path.is_symlink() or not receipt_path.is_file():
                return False
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            stat = path.stat()
            return receipt == {
                "schema_version": "1.0",
                "filename": path.name,
                "size_bytes": stat.st_size,
                "checksum": _sha256_file(path),
            }
        except (OSError, TypeError, ValueError):
            return False

    def restore_colmap(self, key: str, workspace: Path) -> bool:
        """Chỉ chép cache có inventory/checksum khớp; cache hỏng là miss để caller chạy COLMAP thật."""
        source = self._colmap(key)
        if not self._colmap_cache_valid(key, source):
            if source.exists():
                logger.warning("REC-03 bỏ qua COLMAP resume cache không hợp lệ key=%s", key)
            return False
        restore_dir = workspace / f".colmap-restore-{uuid4().hex}"
        restore_dir.mkdir()
        sparse_published = False
        try:
            shutil.copytree(source / "sparse", restore_dir / "sparse")
            prefix = (workspace / "process.log").read_bytes() if (workspace / "process.log").is_file() else b""
            marker = f"REUSED_SPARSE_MODEL key={key}: dùng lại kết quả COLMAP của lần chạy trước; log của lần đó:\n"
            (restore_dir / "process.log").write_bytes(
                prefix + marker.encode("utf-8") + (source / "process.log").read_bytes()
            )
            (restore_dir / "sparse").rename(workspace / "sparse")
            sparse_published = True
            (restore_dir / "process.log").replace(workspace / "process.log")
        except OSError:
            if sparse_published:
                shutil.rmtree(workspace / "sparse", ignore_errors=True)
            raise
        finally:
            shutil.rmtree(restore_dir, ignore_errors=True)
        logger.info("REC-03 dùng lại sparse model key=%s", key)
        return True

    def store_colmap(self, key: str, workspace: Path) -> None:
        """Lưu sparse model đã verify kèm inventory; cache cũ hỏng được giữ làm bằng chứng."""
        target = self._colmap(key)
        staging = self.root / f".staging-{uuid4().hex}"
        staging.mkdir(parents=True)
        shutil.copytree(workspace / "sparse", staging / "sparse")
        shutil.copyfile(workspace / "process.log", staging / "process.log")
        files = self._colmap_inventory(staging)
        if files is None:
            raise ValueError("COLMAP sparse output is incomplete; cache was not stored")
        (staging / _COLMAP_MANIFEST_NAME).write_bytes(self._colmap_manifest_bytes(key, files))
        if target.exists() and not self._colmap_cache_valid(key, target):
            quarantine = self.root / f".invalid-colmap-{key}-{uuid4().hex}"
            target.rename(quarantine)
            logger.warning("REC-03 giữ COLMAP resume cache hỏng tại quarantine key=%s", key)
        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)  # đổi tên sau cùng: không bao giờ có kho dở dang ở đường dẫn thật
        self.clear_checkpoints(key)

    # --- Brush ------------------------------------------------------------

    def checkpoint_dir(self, key: str) -> Path:
        """Nơi Brush xuất checkpoint của khoá này (tạo nếu chưa có)."""
        path = self._brush(key)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def checkpoint_fingerprints(self, key: str) -> dict[str, tuple[int, int]]:
        """Snapshot stat trước khi Brush chạy để chỉ attest file mới/được ghi lại ở attempt này."""
        directory = self._brush(key)
        found: dict[str, tuple[int, int]] = {}
        try:
            candidates = list(directory.glob("ckpt_*.ply"))
        except OSError as error:
            logger.warning("REC-04 không đọc được Brush checkpoint inventory cause=%s", type(error).__name__)
            return found
        for path in candidates:
            if _CHECKPOINT.fullmatch(path.name) and path.is_file() and not path.is_symlink():
                try:
                    stat = path.stat()
                except OSError:
                    continue
                found[path.name] = (stat.st_size, stat.st_mtime_ns)
        return found

    def attest_checkpoints(self, key: str, before: dict[str, tuple[int, int]]) -> None:
        """Attest PLY hoàn chỉnh mới/đã đổi sau khi child process đã dừng; I/O lỗi chỉ làm cache miss."""
        directory = self._brush(key)
        try:
            candidates = list(directory.glob("ckpt_*.ply"))
        except OSError as error:
            logger.warning("REC-04 không đọc được Brush checkpoint inventory cause=%s", type(error).__name__)
            return
        for path in candidates:
            if (
                not _CHECKPOINT.fullmatch(path.name)
                or path.is_symlink()
                or not path.is_file()
                or not ply_is_complete(path)
            ):
                continue
            try:
                stat = path.stat()
                if before.get(path.name) == (stat.st_size, stat.st_mtime_ns):
                    continue
                receipt = {
                    "schema_version": "1.0",
                    "filename": path.name,
                    "size_bytes": stat.st_size,
                    "checksum": _sha256_file(path),
                }
                receipt_path = self._checkpoint_receipt(path)
                temporary = receipt_path.with_name(f".{receipt_path.name}.{uuid4().hex}.tmp")
                temporary.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
                temporary.replace(receipt_path)
            except OSError as error:
                logger.warning("REC-04 không attest Brush checkpoint cause=%s", type(error).__name__)

    def checkpoints(self, key: str) -> dict[int, Path]:
        """`bước → file` của các checkpoint nguyên vẹn. Brush đệm số 0 vào tên theo độ dài tổng số bước
        (`ckpt_02500.ply`), nên luôn đọc số bước từ tên thay vì tự ghép tên."""
        found = {}
        for path in self._brush(key).glob("ckpt_*.ply"):
            match = _CHECKPOINT.fullmatch(path.name)
            if match and ply_is_complete(path) and self._checkpoint_is_attested(path):
                found[int(match.group(1))] = path
        return found

    def latest_checkpoint(self, key: str, below: int) -> tuple[int, Path] | None:
        """Checkpoint nguyên vẹn có số bước lớn nhất và nhỏ hơn `below` (tổng số bước); None nếu không có."""
        earlier = {step: path for step, path in self.checkpoints(key).items() if step < below}
        return max(earlier.items()) if earlier else None

    def clear_checkpoints(self, key: str) -> None:
        """Xoá checkpoint của khoá (train xong, hoặc sparse model đã đổi)."""
        shutil.rmtree(self._brush(key), ignore_errors=True)


def checkpoint_interval(total_steps: int, target: int) -> int:
    """Số bước giữa hai lần xuất, chia hết `total_steps` để lần xuất cuối rơi đúng bước cuối."""
    for count in range(max(1, round(total_steps / max(1, target))), 0, -1):
        if total_steps % count == 0:
            return total_steps // count
    return total_steps
