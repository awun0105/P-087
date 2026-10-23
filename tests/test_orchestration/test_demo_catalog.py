"""Catalog mẫu demo: cơ sở dữ liệu cộng kho file là nguồn sự thật; đĩa chỉ là bộ đệm được sửa lại lúc khởi động."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.samples.bundle import DemoUnavailableError
from src.services.orchestration.samples.catalog import DemoCatalog, SampleFile, SampleRecord, inventory


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
