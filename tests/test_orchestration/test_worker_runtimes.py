"""T-040 bước 2: worker công bố runtime vào DB; API chọn runtime sống theo TTL."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.models.contracts.manifests import RuntimeComponent, RuntimeComponentStatus, RuntimeManifest
from src.services.orchestration.artifacts.checksum import with_canonical_checksum
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.profile import ExecutionProfile, software_runtime_checksum
from src.services.orchestration.jobs.worker_runtimes import RUNTIME_TTL, find, publish, publisher, select

_PLACEHOLDER = "sha256:" + "0" * 64
_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _manifest(*, colmap: str = "3.9.1", gpu: str = "NVIDIA A40", driver: str = "550.90") -> RuntimeManifest:
    def component(version: str) -> RuntimeComponent:
        return RuntimeComponent(status=RuntimeComponentStatus.VERIFIED, version=version)

    draft = RuntimeManifest(
        schema_version="1.0",
        components={
            "colmap": component(colmap),
            "gpu_model": component(gpu),
            "vram": component("48"),
            "nvidia_driver": component(driver),
        },
        runtime_manifest_checksum=_PLACEHOLDER,
    )
    return with_canonical_checksum(draft, "runtime_manifest_checksum")


def _profile(
    manifest: RuntimeManifest, *, config: str = "sha256:" + "c" * 64, seed: int | None = 7
) -> ExecutionProfile:
    return ExecutionProfile(
        config_checksum=config,
        runtime_manifest_checksum=manifest.runtime_manifest_checksum,
        software_runtime_checksum=software_runtime_checksum(manifest),
        seed=seed,
    )


def test_publish_keeps_one_row_per_software_checksum(runtime_database_url: str) -> None:
    database = RuntimeDatabase(runtime_database_url)
    first_seen = _NOW - timedelta(hours=2)
    publish(database, _profile(_manifest(gpu="NVIDIA A40")), _manifest(gpu="NVIDIA A40"), now=first_seen)

    publish(
        database,
        _profile(_manifest(gpu="NVIDIA H100", driver="555.01")),
        _manifest(gpu="NVIDIA H100", driver="555.01"),
        now=_NOW,
    )

    row = select(database, config_checksum="sha256:" + "c" * 64, seed=7, now=_NOW)
    assert row is not None
    assert row.software_runtime_checksum == software_runtime_checksum(_manifest())
    assert row.gpu_name == "NVIDIA H100"
    assert row.hardware["nvidia_driver"] == "555.01"
    assert row.first_seen_at == first_seen
    assert row.last_seen_at == _NOW


def test_select_prefers_a_live_runtime_over_a_newer_stale_one(runtime_database_url: str) -> None:
    database = RuntimeDatabase(runtime_database_url)
    live = _manifest(colmap="3.9.1")
    stale = _manifest(colmap="3.10.0")
    publish(database, _profile(live), live, now=_NOW - RUNTIME_TTL / 2)
    publish(database, _profile(stale), stale, now=_NOW - RUNTIME_TTL * 3)

    chosen = select(database, config_checksum="sha256:" + "c" * 64, seed=7, now=_NOW)

    assert chosen is not None
    assert chosen.software_runtime_checksum == software_runtime_checksum(live)
    assert chosen.is_live(_NOW)


def test_select_falls_back_to_most_recent_when_nothing_is_live(runtime_database_url: str) -> None:
    database = RuntimeDatabase(runtime_database_url)
    older = _manifest(colmap="3.9.1")
    newer = _manifest(colmap="3.10.0")
    publish(database, _profile(older), older, now=_NOW - timedelta(hours=5))
    publish(database, _profile(newer), newer, now=_NOW - timedelta(hours=1))

    chosen = select(database, config_checksum="sha256:" + "c" * 64, seed=7, now=_NOW)

    assert chosen is not None
    assert chosen.software_runtime_checksum == software_runtime_checksum(newer)
    assert not chosen.is_live(_NOW)


def test_select_ignores_other_config_or_seed(runtime_database_url: str) -> None:
    database = RuntimeDatabase(runtime_database_url)
    manifest = _manifest()
    publish(database, _profile(manifest, config="sha256:" + "d" * 64), manifest, now=_NOW)

    assert select(database, config_checksum="sha256:" + "c" * 64, seed=7, now=_NOW) is None
    assert select(database, config_checksum="sha256:" + "d" * 64, seed=8, now=_NOW) is None
    assert select(database, config_checksum="sha256:" + "d" * 64, seed=7, now=_NOW) is not None


def test_publish_rejects_a_manifest_that_is_not_the_locked_profile(runtime_database_url: str) -> None:
    database = RuntimeDatabase(runtime_database_url)
    locked = _manifest(colmap="3.9.1")
    other = _manifest(colmap="3.10.0")

    with pytest.raises(ValueError, match="không khớp profile"):
        publish(database, _profile(locked), other, now=_NOW)
    assert select(database, config_checksum="sha256:" + "c" * 64, seed=7, now=_NOW) is None


def test_find_returns_the_runtime_regardless_of_ttl(runtime_database_url: str) -> None:
    database = RuntimeDatabase(runtime_database_url)
    manifest = _manifest()
    publish(database, _profile(manifest), manifest, now=_NOW - timedelta(days=3))

    found = find(database, software_runtime_checksum(manifest))

    assert found is not None
    assert not found.is_live(_NOW)
    assert find(database, "sha256:" + "e" * 64) is None


def test_publisher_skips_when_config_file_changed_since_startup(tmp_path: Path, runtime_database_url: str) -> None:
    database = RuntimeDatabase(runtime_database_url)
    config = tmp_path / "processing.json"
    config.write_text('{"colmap": {}, "brush": {}}', encoding="utf-8")
    manifest = _manifest()
    runtime = tmp_path / "runtime_manifest.json"
    runtime.write_text(manifest.model_dump_json(), encoding="utf-8")
    profile = ExecutionProfile.load(config, runtime, seed=7)
    publish_current = publisher(config, runtime, profile)

    publish_current(database)
    before = select(database, config_checksum=profile.config_checksum, seed=7)
    assert before is not None

    config.write_text('{"colmap": {"edited": true}, "brush": {}}', encoding="utf-8")
    publish_current(database)

    after = select(database, config_checksum=profile.config_checksum, seed=7)
    assert after is not None
    assert after.last_seen_at == before.last_seen_at
