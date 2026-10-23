"""Catalog mẫu demo: cơ sở dữ liệu cộng kho file là nguồn sự thật; đĩa chỉ là bộ đệm được sửa lại lúc khởi động."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.services.orchestration.artifacts import sha256_file
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.samples import DemoFile, DemoManifest, DemoSource
from src.services.orchestration.samples import catalog as catalog_module
from src.services.orchestration.samples.bundle import DemoUnavailableError
from src.services.orchestration.samples.catalog import (
    DemoCatalog,
    SampleFile,
    SampleRecord,
    SyncReport,
    import_library,
    inventory,
    prepare_library,
    register_bundle,
    sync_library,
)
from tests.test_orchestration.memory_object_store import MemoryObjectStore


def _database(tmp_path: Path) -> RuntimeDatabase:
    return RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")


def _record(sample_id: str, *, job_id: str | None = "job-1", state: str = "published") -> SampleRecord:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    return SampleRecord(
        sample_id=sample_id,
        state=state,
        job_id=job_id,
        manifest_checksum="sha256:" + "a" * 64,
        files=[SampleFile(path="manifest.json", size_bytes=2, checksum="sha256:" + "b" * 64)],
        published_by="reviewer-1",
        published_at=now,
        updated_at=now,
    )


def test_save_get_and_state_roundtrip(tmp_path: Path) -> None:
    catalog = DemoCatalog(_database(tmp_path))
    assert catalog.get("kho") is None and catalog.published_ids() == set()

    catalog.save(_record("kho"))

    stored = catalog.get("kho")
    assert stored == _record("kho") and catalog.is_published("kho") and catalog.published_ids() == {"kho"}
    removed = catalog.set_state("kho", "unpublished")
    assert removed.state == "unpublished" and removed.updated_at >= stored.updated_at
    assert not catalog.is_published("kho") and catalog.records(state="unpublished")[0].sample_id == "kho"
    with pytest.raises(DemoUnavailableError):
        catalog.set_state("khong-co", "published")


def test_by_job_only_returns_published_rows(tmp_path: Path) -> None:
    catalog = DemoCatalog(_database(tmp_path))
    catalog.save(_record("cu", state="unpublished"))
    assert catalog.by_job("job-1") is None
    assert catalog.by_job("job-1", state="unpublished").sample_id == "cu"
    catalog.save(_record("moi"))
    assert catalog.by_job("job-1").sample_id == "moi"


def test_inventory_skips_dotfiles_and_refuses_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "kho"
    (root / "files").mkdir(parents=True)
    (root / "manifest.json").write_text("{}")
    (root / "files" / "scene.sog").write_bytes(b"sog")
    (root / ".unpublished").touch()
    (root / "files" / ".tmp").write_bytes(b"x")

    files = inventory(root)

    assert [file.path for file in files] == ["files/scene.sog", "manifest.json"]
    assert files[0] == SampleFile(
        path="files/scene.sog", size_bytes=3, checksum="sha256:" + hashlib.sha256(b"sog").hexdigest()
    )
    (root / "files" / "link").symlink_to(root / "manifest.json")
    with pytest.raises(ValueError, match="symlink"):
        inventory(root)


def test_payload_survives_json_roundtrip(tmp_path: Path) -> None:
    catalog = DemoCatalog(_database(tmp_path))
    catalog.save(_record("kho", job_id=None))
    with catalog.database.transaction() as tx:
        row = tx.execute("SELECT job_id, payload FROM r2s_demo_samples WHERE sample_id='kho'").fetchone()
    assert row[0] is None and json.loads(row[1])["files"][0]["path"] == "manifest.json"


# --- đăng ký bundle, nhập từ đĩa, đối chiếu và sửa lúc khởi động --------------------------------------------------


def _settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        product_demo_dir=tmp_path / "library",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        artifact_root=tmp_path / "artifacts",
        **overrides,
    )


def _bundle(library: Path, sample_id: str, *, job_id: str = "job-1", payload: bytes = b"sog") -> Path:
    root = library / sample_id
    (root / "files").mkdir(parents=True)
    (root / "files" / "scene.sog").write_bytes(payload)
    manifest = DemoManifest(
        demo_id=sample_id,
        title=f"Mẫu {sample_id}",
        origin="pipeline_job",
        source=DemoSource(dataset="Test", sequence="x"),
        produced_at=datetime(2026, 10, 1, tzinfo=UTC),
        provenance={"job_id": job_id},
        stages=[],
        splat=DemoFile(
            name="scene.sog",
            media_type="application/octet-stream",
            size_bytes=len(payload),
            checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        ),
    )
    (root / "manifest.json").write_text(manifest.model_dump_json())
    return root


def _with_store(monkeypatch: pytest.MonkeyPatch) -> MemoryObjectStore:
    store = MemoryObjectStore()
    monkeypatch.setattr(catalog_module, "artifact_remote", lambda settings: SimpleNamespace(store=store))
    return store


def test_register_bundle_uploads_every_file_once_and_saves_the_row(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = _with_store(monkeypatch)
    catalog = DemoCatalog(RuntimeDatabase(settings.database_url))
    root = _bundle(settings.product_demo_dir, "kho")

    record = register_bundle(settings, catalog, root, actor="reviewer-1")

    assert record.state == "published" and record.job_id == "job-1" and record.published_by == "reviewer-1"
    assert sorted(store.objects) == ["demo/library/kho/files/scene.sog", "demo/library/kho/manifest.json"]
    assert store.puts == 2 and catalog.get("kho") == record
    register_bundle(settings, catalog, root, actor="reviewer-1")
    assert store.puts == 2


def test_register_bundle_without_store_only_writes_the_row(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(catalog_module, "artifact_remote", lambda settings: None)
    catalog = DemoCatalog(RuntimeDatabase(settings.database_url))
    root = _bundle(settings.product_demo_dir, "kho")
    record = register_bundle(settings, catalog, root, actor=None, state="unpublished")
    assert record.state == "unpublished" and [file.path for file in record.files] == [
        "files/scene.sog",
        "manifest.json",
    ]


def test_register_bundle_reuploads_an_object_that_lacks_checksum_metadata(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = _with_store(monkeypatch)
    root = _bundle(settings.product_demo_dir, "kho")
    store.objects["demo/library/kho/files/scene.sog"] = (b"sog", None)
    store.puts = 0
    register_bundle(settings, DemoCatalog(RuntimeDatabase(settings.database_url)), root, actor=None)
    assert store.puts == 2 and store.objects["demo/library/kho/files/scene.sog"][1] is not None


def test_register_bundle_refuses_an_object_with_other_bytes(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = _with_store(monkeypatch)
    catalog = DemoCatalog(RuntimeDatabase(settings.database_url))
    root = _bundle(settings.product_demo_dir, "kho")
    (tmp_path / "other").write_bytes(b"khac")
    store.put_file("demo/library/kho/files/scene.sog", tmp_path / "other", "sha256:" + "f" * 64)
    with pytest.raises(ValueError, match="different bytes"):
        register_bundle(settings, catalog, root, actor=None)
    assert catalog.get("kho") is None


def test_sync_repairs_a_deleted_file_from_the_store(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    _with_store(monkeypatch)
    catalog = DemoCatalog(RuntimeDatabase(settings.database_url))
    root = _bundle(settings.product_demo_dir, "kho")
    register_bundle(settings, catalog, root, actor=None)
    (root / "files" / "scene.sog").write_bytes(b"bi sua")
    register_bundle(settings, catalog, _bundle(settings.product_demo_dir, "mat", job_id="job-2"), actor=None)
    shutil.rmtree(settings.product_demo_dir / "mat")

    report = sync_library(settings, catalog)

    assert report.repaired == ["kho", "mat"] and report.verified == [] and report.broken == []
    assert (root / "files" / "scene.sog").read_bytes() == b"sog"
    assert (settings.product_demo_dir / "mat" / "manifest.json").is_file()
    assert sync_library(settings, catalog).verified == ["kho", "mat"]


def test_sync_reports_a_sample_nobody_can_provide_and_keeps_the_rest(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = _with_store(monkeypatch)
    catalog = DemoCatalog(RuntimeDatabase(settings.database_url))
    register_bundle(settings, catalog, _bundle(settings.product_demo_dir, "tot"), actor=None)
    register_bundle(settings, catalog, _bundle(settings.product_demo_dir, "hong", job_id="job-2"), actor=None)
    (settings.product_demo_dir / "hong" / "files" / "scene.sog").unlink()
    del store.objects["demo/library/hong/files/scene.sog"]

    report = sync_library(settings, catalog)

    assert report.verified == ["tot"] and report.broken == ["hong"] and report.repaired == []
    monkeypatch.setattr(catalog_module, "artifact_remote", lambda settings: None)
    assert sync_library(settings, catalog).broken == ["hong"]


def test_import_registers_disk_bundles_as_published_and_ignores_the_legacy_table(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    _with_store(monkeypatch)
    database = RuntimeDatabase(settings.database_url)
    catalog = DemoCatalog(database)
    _bundle(settings.product_demo_dir, "moi")
    _bundle(settings.product_demo_dir, "bo-trong-db", job_id="job-2")
    (_bundle(settings.product_demo_dir, "bo-tren-dia", job_id="job-3") / ".unpublished").touch()
    (settings.product_demo_dir / ".tmp-dang-xuat").mkdir()
    (settings.product_demo_dir / "khong-manifest").mkdir()
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_demo_unpublished(sample_id, at) VALUES ('bo-trong-db', '2026-10-01T00:00:00+00:00')"
        )

    assert import_library(settings, catalog) == ["bo-tren-dia", "bo-trong-db", "moi"]

    assert catalog.published_ids() == {"moi", "bo-trong-db"}
    assert {record.sample_id for record in catalog.records(state="unpublished")} == {"bo-tren-dia"}
    assert import_library(settings, catalog) == []


def test_import_does_not_reupload_objects_already_in_the_store(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    store = _with_store(monkeypatch)
    root = _bundle(settings.product_demo_dir, "kho")
    for path in ("manifest.json", "files/scene.sog"):
        store.put_file(f"demo/library/kho/{path}", root / path, sha256_file(root / path))
    store.puts = 0

    import_library(settings, DemoCatalog(RuntimeDatabase(settings.database_url)))

    assert store.puts == 0


def test_prepare_seeds_from_the_pinned_archive_once(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(
        tmp_path,
        product_demo_archive_key="demo/releases/v1.zip",
        product_demo_archive_checksum="sha256:" + "c" * 64,
        product_demo_required=True,
    )
    _with_store(monkeypatch)
    calls: list[str] = []

    def fake_bootstrap(current: Settings) -> None:
        calls.append(current.product_demo_archive_key or "")
        _bundle(current.product_demo_dir, "goc")

    monkeypatch.setattr("src.services.orchestration.samples.release.bootstrap_library", fake_bootstrap)
    database = RuntimeDatabase(settings.database_url)

    first = prepare_library(settings, database)
    shutil.rmtree(settings.product_demo_dir / "goc")
    second = prepare_library(settings, database)

    assert calls == ["demo/releases/v1.zip"]
    assert first.verified == ["goc"] and second.repaired == ["goc"]
    DemoCatalog(database).set_state("goc", "unpublished")
    assert prepare_library(settings, database) == SyncReport()  # bắt buộc có demo nhưng không chết; readiness báo chờ
