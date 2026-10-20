"""Đệm lưới va chạm Walk đã dựng theo revision scene (T-052).

Dựng lưới va chạm tổng hợp của một revision tốn tới ~1 giây CPU và chặn mọi request khác của API. Revision scene bất
biến, nên kết quả được dựng một lần cho mỗi khoá rồi giữ trong bộ nhớ và trên đĩa (sống qua khởi động lại). Kiểm quyền và
kiểm revision luôn chạy trước khi đọc đệm; đệm chỉ thay phần dựng.
"""

import hashlib
import json
import logging
import os
import tempfile
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Literal

logger = logging.getLogger(__name__)

#: Tổng byte giữ trong bộ nhớ của một tiến trình API.
_MEMORY_BYTES = 256 * 1024 * 1024
_MEMORY_ENTRIES = 4


@dataclass(frozen=True)
class CollisionKey:
    job_id: str
    scene_revision: str
    source_checksum: str
    preview: bool
    frame: Literal["display", "canonical"]
    config_checksum: str
    #: URI nguồn đã kiểm khớp revision lúc dựng; khoá gồm cả URI để lần trúng đệm vẫn gắn đúng nguồn.
    source_uri: str = ""

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode("utf-8")).hexdigest()

    @property
    def etag(self) -> str:
        """ETag biết trước khi dựng: cùng khoá thì cùng nội dung."""
        return f'"wc-{self.digest[:40]}"'


@dataclass(frozen=True)
class CollisionPayload:
    body: bytes
    identity: str
    shared: int
    floor: int
    repaired: int


class WalkCollisionCache:
    """Bộ nhớ (LRU, giới hạn byte) + đĩa (`root`, None = chỉ bộ nhớ); mỗi khoá dựng đúng một lần kể cả khi gọi đồng thời."""

    def __init__(self, root: Path | None) -> None:
        self.root = root
        self._memory: OrderedDict[str, CollisionPayload] = OrderedDict()
        self._lock = Lock()
        self._key_locks: dict[str, Lock] = {}

    def get_or_build(self, key: CollisionKey, build: Callable[[], CollisionPayload]) -> CollisionPayload:
        digest = key.digest
        with self._lock:
            found = self._memory.get(digest)
            if found is not None:
                self._memory.move_to_end(digest)
                return found
            key_lock = self._key_locks.setdefault(digest, Lock())
        with key_lock:
            with self._lock:
                found = self._memory.get(digest)
            if found is None:
                found = self._read_disk(digest)
            if found is None:
                found = build()
                self._write_disk(digest, found)
            self._remember(digest, found)
        with self._lock:
            self._key_locks.pop(digest, None)
        return found

    def prune(self, *, max_age_days: float = 7) -> int:
        """Xoá file đệm không dùng quá `max_age_days`; trả số file đã xoá."""
        if self.root is None or not self.root.is_dir():
            return 0
        cutoff = time.time() - max_age_days * 86400
        removed = 0
        for path in self.root.iterdir():
            try:
                if path.is_file() and path.stat().st_atime < cutoff and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    def _remember(self, digest: str, payload: CollisionPayload) -> None:
        with self._lock:
            self._memory[digest] = payload
            self._memory.move_to_end(digest)
            while len(self._memory) > 1 and (
                len(self._memory) > _MEMORY_ENTRIES
                or sum(len(item.body) for item in self._memory.values()) > _MEMORY_BYTES
            ):
                self._memory.popitem(last=False)

    def _paths(self, digest: str) -> tuple[Path, Path] | None:
        if self.root is None:
            return None
        return self.root / f"{digest}.glb", self.root / f"{digest}.json"

    def _read_disk(self, digest: str) -> CollisionPayload | None:
        paths = self._paths(digest)
        if paths is None:
            return None
        body_path, meta_path = paths
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = body_path.read_bytes()
            if hashlib.sha256(body).hexdigest() != meta["body_sha256"]:
                return None
            os.utime(body_path)
            return CollisionPayload(
                body=body,
                identity=meta["identity"],
                shared=meta["shared"],
                floor=meta["floor"],
                repaired=meta["repaired"],
            )
        except (OSError, ValueError, KeyError):
            return None

    def _write_disk(self, digest: str, payload: CollisionPayload) -> None:
        paths = self._paths(digest)
        if paths is None:
            return
        body_path, meta_path = paths
        meta = {
            "identity": payload.identity,
            "shared": payload.shared,
            "floor": payload.floor,
            "repaired": payload.repaired,
            "body_sha256": hashlib.sha256(payload.body).hexdigest(),
        }
        try:
            body_path.parent.mkdir(parents=True, exist_ok=True)
            for path, data in ((body_path, payload.body), (meta_path, json.dumps(meta).encode("utf-8"))):
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                    handle.write(data)
                os.replace(handle.name, path)
        except OSError as error:
            logger.warning("Không ghi được đệm lưới va chạm cause=%s", type(error).__name__)
