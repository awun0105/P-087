"""T-052: composed walk collision is built once per scene revision and frame."""

import threading
import time
from pathlib import Path

from src.services.orchestration.scene import collision_cache
from src.services.orchestration.scene.collision_cache import CollisionKey, CollisionPayload, WalkCollisionCache


def _key(**update: object) -> CollisionKey:
    values = dict(
        job_id="job-a",
        scene_revision="rev-002",
        source_checksum="sha256:" + "1" * 64,
        preview=False,
        frame="display",
        config_checksum="sha256:" + "2" * 64,
    )
    values.update(update)
    return CollisionKey(**values)


def _payload(body: bytes = b"glb") -> CollisionPayload:
    return CollisionPayload(body=body, identity="id-1", shared=1, floor=2, repaired=3)


def test_build_runs_once_per_key(tmp_path: Path) -> None:
    cache = WalkCollisionCache(tmp_path)
    builds: list[int] = []
    build = lambda: builds.append(1) or _payload()  # noqa: E731
    assert cache.get_or_build(_key(), build) == _payload()
    assert cache.get_or_build(_key(), build) == _payload()
    assert len(builds) == 1


def test_concurrent_requests_build_once(tmp_path: Path) -> None:
    cache = WalkCollisionCache(tmp_path)
    builds: list[int] = []

    def slow() -> CollisionPayload:
        builds.append(1)
        time.sleep(0.2)
        return _payload()

    threads = [threading.Thread(target=cache.get_or_build, args=(_key(), slow)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(builds) == 1


def test_disk_cache_survives_process_memory_reset(tmp_path: Path) -> None:
    WalkCollisionCache(tmp_path).get_or_build(_key(), lambda: _payload(b"from-disk"))
    fresh = WalkCollisionCache(tmp_path)
    assert fresh.get_or_build(_key(), lambda: (_ for _ in ()).throw(AssertionError("rebuilt"))) == _payload(
        b"from-disk"
    )


def test_different_frame_is_a_different_entry(tmp_path: Path) -> None:
    cache = WalkCollisionCache(tmp_path)
    cache.get_or_build(_key(frame="display"), lambda: _payload(b"display"))
    assert cache.get_or_build(_key(frame="canonical"), lambda: _payload(b"canonical")).body == b"canonical"
    assert _key(frame="display").etag != _key(frame="canonical").etag


def test_memory_cache_respects_size_limit(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(collision_cache, "_MEMORY_BYTES", 10)
    cache = WalkCollisionCache(None)
    cache.get_or_build(_key(scene_revision="rev-1"), lambda: _payload(b"x" * 8))
    cache.get_or_build(_key(scene_revision="rev-2"), lambda: _payload(b"y" * 8))
    assert len(cache._memory) == 1


def test_unwritable_disk_falls_back_to_memory(tmp_path: Path) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    cache = WalkCollisionCache(blocked / "cache")
    assert cache.get_or_build(_key(), _payload) == _payload()


def test_old_cache_files_are_pruned(tmp_path: Path) -> None:
    import os

    cache = WalkCollisionCache(tmp_path)
    cache.get_or_build(_key(), _payload)
    old = time.time() - 8 * 86400
    for path in tmp_path.iterdir():
        os.utime(path, (old, old))
    assert cache.prune(max_age_days=7) >= 1
    assert list(tmp_path.iterdir()) == []
