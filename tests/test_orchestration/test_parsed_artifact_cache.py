"""T-053: parsed artifacts are loaded once per (uri, checksum) per process."""

import threading
import time

from src.services.orchestration.artifacts.parsed_cache import ParsedArtifactCache


def test_loads_once_per_checksum() -> None:
    cache: ParsedArtifactCache[str] = ParsedArtifactCache(4)
    loads: list[int] = []
    assert cache.get_or_load(("u", "c1"), lambda: loads.append(1) or "v") == "v"
    assert cache.get_or_load(("u", "c1"), lambda: loads.append(1) or "v") == "v"
    assert len(loads) == 1


def test_new_checksum_loads_again() -> None:
    cache: ParsedArtifactCache[str] = ParsedArtifactCache(4)
    cache.get_or_load(("u", "c1"), lambda: "a")
    assert cache.get_or_load(("u", "c2"), lambda: "b") == "b"


def test_lru_evicts_oldest() -> None:
    cache: ParsedArtifactCache[str] = ParsedArtifactCache(2)
    cache.get_or_load(("u", "1"), lambda: "1")
    cache.get_or_load(("u", "2"), lambda: "2")
    cache.get_or_load(("u", "1"), lambda: "x")  # touch 1
    cache.get_or_load(("u", "3"), lambda: "3")
    assert cache.get_or_load(("u", "1"), lambda: "never") == "1"  # recently used, kept
    assert cache.get_or_load(("u", "2"), lambda: "reloaded") == "reloaded"  # oldest, evicted


def test_concurrent_get_loads_once() -> None:
    cache: ParsedArtifactCache[str] = ParsedArtifactCache(4)
    loads: list[int] = []

    def slow() -> str:
        loads.append(1)
        time.sleep(0.1)
        return "v"

    threads = [threading.Thread(target=cache.get_or_load, args=(("u", "c"), slow)) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(loads) == 1


def test_failed_load_is_not_cached() -> None:
    cache: ParsedArtifactCache[str] = ParsedArtifactCache(4)

    def broken() -> str:
        raise ValueError("bad")

    try:
        cache.get_or_load(("u", "c"), broken)
    except ValueError:
        pass
    assert cache.get_or_load(("u", "c"), lambda: "ok") == "ok"
