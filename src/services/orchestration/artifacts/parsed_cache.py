"""Đệm đối tượng đã parse + kiểm theo (URI, checksum) trong một tiến trình (T-053).

Artifact gắn checksum là bất biến, nên bản đã parse và kiểm một lần dùng lại được cho mọi request sau. Đối tượng trả
ra phải được coi là chỉ đọc: chỗ cần sửa dùng `model_copy`, không sửa tại chỗ.
"""

from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar

T = TypeVar("T")


class ParsedArtifactCache(Generic[T]):
    """LRU có khoá luồng; cùng khoá gọi đồng thời chỉ nạp một lần; nạp lỗi thì không lưu."""

    def __init__(self, max_entries: int) -> None:
        self.max_entries = max_entries
        self._items: OrderedDict[tuple[str, str], T] = OrderedDict()
        self._lock = Lock()
        self._loading: dict[tuple[str, str], Lock] = {}

    def get_or_load(self, key: tuple[str, str], load: Callable[[], T]) -> T:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
            key_lock = self._loading.setdefault(key, Lock())
        with key_lock:
            with self._lock:
                if key in self._items:
                    self._items.move_to_end(key)
                    return self._items[key]
            try:
                value = load()
            finally:
                with self._lock:
                    self._loading.pop(key, None)
            with self._lock:
                self._items[key] = value
                self._items.move_to_end(key)
                while len(self._items) > self.max_entries:
                    self._items.popitem(last=False)
            return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
