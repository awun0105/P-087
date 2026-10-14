"""Unused uploads are disposable; accepted scene evidence is not."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.models.contracts.input_assembly import InputAssemblyDeclarations
from src.services.orchestration.artifacts import ArtifactRemote, ArtifactResolver
from src.services.orchestration.inputs.assembly import InputAssemblyService
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.uploads import DirectUploadService, VideoUploadService
from src.services.orchestration.uploads.temporary import TemporaryUploadService
from tests.test_orchestration.memory_object_store import MemoryObjectStore

VIDEO = b"\x00\x00\x00\x18ftypmp42"


@pytest.fixture
def uploads(tmp_path: Path) -> VideoUploadService:
    return VideoUploadService(
        RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}"), ArtifactResolver(tmp_path / "files"), 1024
    )


def _upload(uploads: VideoUploadService, *, temporary: bool = True) -> str:
    pending = uploads.begin("input.mp4")
    pending.publication.write(VIDEO)
    return uploads.finish(pending, temporary=temporary).upload_id


def test_discard_removes_source_sidecars_and_draft_database_rows(uploads: VideoUploadService) -> None:
    upload_id = _upload(uploads)
    uploads.stage_for_assembly(upload_id)
    assembly_service = InputAssemblyService(uploads.database, resolver=uploads.resolver)
    assembly = assembly_service.create("anonymous", [upload_id], InputAssemblyDeclarations(), [], None)
    namespace = uploads.resolver.artifact_root / "jobs" / upload_id
    (namespace / "input" / "frame-map.jsonl").write_text("{}")
    with uploads.database.transaction() as tx:
        assert tx.execute("SELECT 1 FROM r2s_uploads WHERE upload_id=?", (upload_id,)).fetchone()
    cleanup = TemporaryUploadService(uploads.database, uploads.resolver)
    assert cleanup.discard([upload_id], "anonymous") == [upload_id]
    assert not namespace.exists()
    with uploads.database.transaction() as tx:
        for table in ("r2s_uploads", "r2s_input_uploads", "r2s_temporary_uploads"):
            assert not tx.execute(f"SELECT 1 FROM {table} WHERE upload_id=?", (upload_id,)).fetchone()
        assert not tx.execute(
            "SELECT 1 FROM r2s_input_assemblies WHERE assembly_id=?", (assembly.snapshot.assembly_id,)
        ).fetchone()
    assert cleanup.discard([upload_id], "anonymous") == []


def test_only_owner_can_discard_or_renew(uploads: VideoUploadService) -> None:
    upload_id = _upload(uploads)
    service = TemporaryUploadService(uploads.database, uploads.resolver)
    for operation in (service.discard, service.renew):
        with pytest.raises(PermissionError):
            operation([upload_id], "someone-else")
    assert uploads.resolver.require_uri(uploads.get(upload_id).artifact_uri, uploads.get(upload_id).checksum).is_file()


def test_project_link_protects_source_even_after_expiry(uploads: VideoUploadService) -> None:
    upload_id = _upload(uploads)
    uploads.link_project(upload_id, "project-accepted")
    service = TemporaryUploadService(uploads.database, uploads.resolver)
    assert service.discard([upload_id], "anonymous") == []
    assert service.purge_expired(datetime.now(UTC) + timedelta(days=2)) == []
    assert uploads.resolver.resolve(uploads.get(upload_id).artifact_uri).is_file()


@pytest.mark.parametrize("table", ["r2s_imports", "r2s_projects"])
def test_import_and_project_references_preserve_unlinked_sources(uploads: VideoUploadService, table: str) -> None:
    upload_id = _upload(uploads)
    with uploads.database.transaction(write=True) as tx:
        identifier = "import_id" if table == "r2s_imports" else "project_id"
        columns = f"{identifier},upload_id,payload" if table == "r2s_imports" else f"{identifier},payload"
        values = (
            ("accepted", upload_id, '{"upload_id":"' + upload_id + '"}')
            if table == "r2s_imports"
            else ("accepted", '{"upload_id":"' + upload_id + '"}')
        )
        tx.execute(f"INSERT INTO {table}({columns}) VALUES ({','.join('?' for _ in values)})", values)
    assert TemporaryUploadService(uploads.database, uploads.resolver).discard([upload_id], "anonymous") == []
    assert uploads.resolver.resolve(uploads.get(upload_id).artifact_uri).is_file()


def test_expiry_fallback_and_heartbeat(uploads: VideoUploadService) -> None:
    upload_id = _upload(uploads)
    service = TemporaryUploadService(uploads.database, uploads.resolver)
    with uploads.database.transaction(write=True) as tx:
        tx.execute(
            "UPDATE r2s_temporary_uploads SET expires_at=?", ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(),)
        )
    service.renew([upload_id], "anonymous")
    assert service.purge_expired() == []
    assert service.purge_expired(datetime.now(UTC) + timedelta(days=2)) == [upload_id]


def test_run_reservation_prevents_navigation_cleanup_race(uploads: VideoUploadService) -> None:
    upload_id = _upload(uploads)
    service = TemporaryUploadService(uploads.database, uploads.resolver)
    service.reserve([upload_id])
    assert service.discard([upload_id], "anonymous") == []
    assert uploads.resolver.resolve(uploads.get(upload_id).artifact_uri).is_file()
    assert service.purge_expired(datetime.now(UTC) + timedelta(days=2)) == [upload_id]


def test_deleting_upload_cannot_be_accepted_by_run(uploads: VideoUploadService) -> None:
    upload_id = _upload(uploads)
    with uploads.database.transaction(write=True) as tx:
        tx.execute("UPDATE r2s_temporary_uploads SET deleting=1 WHERE upload_id=?", (upload_id,))
    with pytest.raises(RuntimeStateConflictError):
        TemporaryUploadService(uploads.database, uploads.resolver).reserve([upload_id])


def test_abandoned_source_cannot_recreate_draft_metadata(uploads: VideoUploadService) -> None:
    upload_id = _upload(uploads)
    uploads.stage_for_assembly(upload_id)
    service = InputAssemblyService(uploads.database, resolver=uploads.resolver)
    stored = service.create("anonymous", [upload_id], InputAssemblyDeclarations(), [], None)
    cleanup = TemporaryUploadService(uploads.database, uploads.resolver)
    cleanup.discard([upload_id], "anonymous")
    with pytest.raises(RuntimeStateConflictError):
        cleanup.reserve([upload_id])
    from src.services.orchestration.inputs.assembly import InputAssemblyConflictError

    with pytest.raises(InputAssemblyConflictError):
        service._persist_snapshot(stored, None)


def test_legacy_unused_upload_can_be_adopted_but_used_upload_is_preserved(uploads: VideoUploadService) -> None:
    unused = _upload(uploads, temporary=False)
    used = _upload(uploads, temporary=False)
    uploads.link_project(used, "accepted-project")
    service = TemporaryUploadService(uploads.database, uploads.resolver)
    service.renew([unused, used], "anonymous")
    assert service.discard([unused, used], "anonymous") == [unused]
    assert uploads.get(used)


def test_namespace_symlink_never_deletes_other_files(uploads: VideoUploadService, tmp_path: Path) -> None:
    upload_id = _upload(uploads)
    namespace = uploads.resolver.artifact_root / "jobs" / upload_id
    moved = tmp_path / "must-survive"
    namespace.rename(moved)
    namespace.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        TemporaryUploadService(uploads.database, uploads.resolver).discard([upload_id], "anonymous")
    assert (moved / "input/source.mp4").is_file()


def test_remote_failure_keeps_metadata_for_retry(uploads: VideoUploadService, monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = _upload(uploads)
    remote = ArtifactRemote(MemoryObjectStore())
    uploads.resolver.remote = remote
    original = remote.delete_tree

    def fail_delete(_: str) -> int:
        raise OSError("offline")

    monkeypatch.setattr(remote, "delete_tree", fail_delete)
    service = TemporaryUploadService(uploads.database, uploads.resolver)
    with pytest.raises(OSError):
        service.discard([upload_id], "anonymous")
    assert uploads.get(upload_id)
    monkeypatch.setattr(remote, "delete_tree", original)
    assert service.discard([upload_id], "anonymous") == [upload_id]


def test_direct_partial_upload_is_aborted_and_completed_remote_source_is_deleted(tmp_path: Path) -> None:
    store = MemoryObjectStore()
    resolver = ArtifactResolver(tmp_path / "files", ArtifactRemote(store))
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    direct = DirectUploadService(database, resolver, 1024)
    partial = direct.begin("input.mp4", len(VIDEO), temporary=True)
    cleanup = TemporaryUploadService(database, resolver)
    assert cleanup.discard([partial.upload_id], "anonymous") == [partial.upload_id]
    complete = direct.begin("input.mp4", len(VIDEO), temporary=True)
    store.upload_part(complete.multipart_id, 1, VIDEO)
    direct.complete(complete.upload_id)
    direct.verify(complete.upload_id)
    assert cleanup.discard([complete.upload_id], "anonymous") == [complete.upload_id]
    assert not store.list_objects("jobs/")
