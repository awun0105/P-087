"""Chịu lỗi DB thoáng qua trong các luồng gia hạn lease / kiểm hủy (T-049).

Một lần DB chập chờn không được giết lượt GPU đang chạy dài; chỉ bỏ cuộc khi lỗi không phải lỗi thoáng qua, hoặc
khi đã quá 2/3 TTL lease kể từ lần thành công gần nhất (lease có thể đã thật sự mất).
"""

import logging
import time
from collections.abc import Callable
from datetime import timedelta

from src.services.orchestration.jobs.database import is_transient_database_error

logger = logging.getLogger(__name__)


class HeartbeatTolerance:
    """Theo dõi lần gia hạn thành công gần nhất và quyết định có chịu thêm một lỗi hay không."""

    def __init__(self, ttl: timedelta, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._window = ttl.total_seconds() * 2 / 3
        self._clock = clock
        self._last_success = clock()

    def succeeded(self) -> None:
        self._last_success = self._clock()

    def tolerate(self, error: BaseException) -> bool:
        """True = bỏ qua lỗi này, thử lại nhịp sau; False = dừng như mất lease."""
        if not is_transient_database_error(error):
            return False
        waited = self._clock() - self._last_success
        if waited >= self._window:
            return False
        logger.warning("Lỗi DB thoáng qua (%s); chịu thêm, đã %.0f s từ lần thành công", type(error).__name__, waited)
        return True
