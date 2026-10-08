"""Gỡ scene khỏi Studio: DB và thư mục phải đi cùng nhau, khôi phục được, và từ chối khi chưa an toàn."""

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import ExecutionError, JobStatus, StageId
from src.services.orchestration.artifacts import ArtifactRemote
from src.services.orchestration.artifacts.checksum import sha256_bytes
from src.services.orchestration.auth.models import Actor
from src.services.orchestration.auth.service import AuthService
from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeStateConflictError
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.projects import JobNotFoundError, ProjectNotFoundError, delete_cli, deletion
from src.services.orchestration.projects.deletion import (
    RECORD_NAME,
    DeletionContext,
    DeletionRefusedError,
    DeletionRequest,
    GuestOwnershipError,
    apply_deletion,
    get_trash_entry,
    import_legacy_entry,
    list_trash,
    plan_deletion,
    purge_deletion,
    purge_expired,
    restore_deletion,
)
from src.services.orchestration.projects.models import (
    DataOrigin,
    JobCreateInput,
    SourceRightsAttestation,
    UploadProjectInput,
)
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.heads import (
    SceneHeadBackfillItem,
    SceneHeadRepairRecord,
    SceneHeadRepository,
)
from src.services.orchestration.uploads import UploadRecord, VideoUploadService
from src.services.orchestration.uploads import scene_imports as imports_module
from src.services.orchestration.uploads.scene_imports import ImportService
from tests.test_orchestration.memory_object_store import MemoryObjectStore
from tests.test_reconstruction.test_input_detection import _gaussian

MP4 = b"\x00\x00\x00\x18ftypmp42"
_TABLES = (
    "r2s_projects",
    "r2s_jobs",
    "r2s_job_events",
    "r2s_scene_requests",
    "r2s_scene_heads",
    "r2s_scene_head_repairs",
    "r2s_scene_head_backfill_items",
    "r2s_scene_publications",
    "r2s_uploads",
    "r2s_upload_sessions",
    "r2s_imports",
)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Registry bền (SQLite + kho artifact tạm) dùng đúng các service mà Studio dùng để tạo scene."""
    config = tmp_path / "processing.json"
    config.write_text(json.dumps({"colmap": {}, "brush": {}}))
    profile = ExecutionProfile(
        config_checksum="sha256:" + hashlib.sha256(config.read_bytes()).hexdigest(),
        runtime_manifest_checksum="sha256:" + "d" * 64,
    )
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts", database=database, execution_profile=profile)

    def fake_package(source: Path, workspace: Path, gpu_index: int | None) -> Path:
        workspace.mkdir(parents=True)
        (workspace / "scene.sog").write_bytes(b"sog:" + source.read_bytes()[:16])
        return workspace / "scene.sog"

    monkeypatch.setattr(imports_module, "package_splat", fake_package)
    return SimpleNamespace(
        root=tmp_path,
        database=database,
        registry=registry,
        uploads=VideoUploadService(database, registry.runtime_resolver, 8 * 1024 * 1024),
        imports=ImportService(database, registry.runtime_resolver, tmp_path / "workers" / "imports"),
        context=DeletionContext(
            database, registry.runtime_resolver, tmp_path / "workers", tmp_path / "rerun", tmp_path / "trash"
        ),
        trash=tmp_path / "trash",
    )


def _upload(
    world: SimpleNamespace,
    name: str = "walk.mp4",
    payload: bytes = MP4 + b"video",
    uploaded_by: Actor | None = None,
) -> UploadRecord:
    pending = world.uploads.begin(name)
    pending.publication.write(payload)
    return world.uploads.finish(pending, uploaded_by)


def _scene(
    world: SimpleNamespace,
    upload: UploadRecord,
    name: str,
    *,
    stopped: bool = True,
    created_by: Actor | None = None,
    owner_user_id: str | None = None,
) -> tuple[str, str]:
    """Scene tạo như API `/scenes/from-upload`; `stopped` huỷ job để scene ở trạng thái gỡ được."""
    attestation = SourceRightsAttestation(
        data_origin=DataOrigin.SELF_COLLECTED_NO_PII,
        declared_owner="Test",
        declared_purpose="Xoá scene",
        rights_to_use_confirmed=True,
        anonymization_confirmed=True,
        retention_acknowledged=True,
    )
    request = UploadProjectInput(upload_id=upload.upload_id, name=name, attestation=attestation)
    project = world.registry.create_project_from_upload(upload, request, "self_attested", created_by=created_by)
    world.uploads.link_project(upload.upload_id, project.project_id)
    job = world.registry.create_job(
        JobCreateInput(project_id=project.project_id),
        requested_by=created_by if owner_user_id is not None else None,
        owner_user_id=owner_user_id,
    )
    if stopped:
        world.registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.CANCELLED))
    workspace = world.root / "workers" / job.job_id / "attempt-1"
    workspace.mkdir(parents=True)
    (workspace / "log.txt").write_text("log")
    (world.root / "rerun").mkdir(exist_ok=True)
    (world.root / "rerun" / f"{job.job_id}.rrd").write_bytes(b"rrd")
    return project.project_id, job.job_id


def _import(world: SimpleNamespace, upload: UploadRecord, name: str) -> str:
    record = world.imports.create(upload, name, None)
    return world.imports.package(record.import_id, upload, None).import_id


def _rows(world: SimpleNamespace) -> dict[str, list[tuple]]:
    with world.database.transaction() as tx:
        return {table: sorted(tx.execute(f"SELECT * FROM {table}").fetchall()) for table in _TABLES}


def _files(world: SimpleNamespace) -> dict[str, str]:
    """Mọi file đang dùng (kho artifact, thư mục worker, bản ghi Rerun) kèm checksum."""
    found = {}
    for area in ("artifacts", "workers", "rerun"):
        for path in sorted((world.root / area).rglob("*")):
            if path.is_file():
                found[str(path.relative_to(world.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def _delete(world: SimpleNamespace, **ids: list[str] | bool) -> str:
    """Gỡ và trả entry_id của mục thùng rác vừa tạo."""
    return apply_deletion(world.context, DeletionRequest(**ids)).entry_id


def _in_trash(world: SimpleNamespace) -> list[str]:
    return [record.entry_id for record in list_trash(world.database)]


def _refused(world: SimpleNamespace, match: str, **ids: list[str] | bool) -> None:
    """Yêu cầu bị từ chối thì không được đổi DB, file hay để lại thư mục thùng rác."""
    rows, files = _rows(world), _files(world)
    with pytest.raises(DeletionRefusedError, match=match):
        _delete(world, **ids)
    assert (_rows(world), _files(world)) == (rows, files)
    assert _in_trash(world) == [] and (not world.trash.exists() or not list(world.trash.iterdir()))


def test_plan_lists_what_would_go_and_changes_nothing(world: SimpleNamespace) -> None:
    project_id, job_id = _scene(world, _upload(world), "Kho A")
    rows, files = _rows(world), _files(world)

    plan = plan_deletion(world.context, DeletionRequest(project_ids=[project_id]))

    assert plan.blockers == []
    assert [(line.kind, line.name) for line in plan.summary] == [("scene", "Kho A"), ("upload", "walk.mp4")]
    assert f"{job_id} CANCELLED" in plan.summary[0].detail
    assert {(item.kind, item.name) for item in plan.items} >= {
        ("artifact", job_id),
        ("artifact", project_id),
        ("worker", job_id),
        ("rerun", job_id),
    }
    assert plan.size_bytes > 0
    assert (_rows(world), _files(world)) == (rows, files)


def test_job_owner_survives_operator_attempt_update_and_trash_restore(world: SimpleNamespace) -> None:
    guest = Actor(user_id="guest-1", display_name="Guest One", role="guest")
    editor = Actor(user_id="editor-1", display_name="Editor One", role="editor")
    upload = _upload(world, uploaded_by=guest)
    project_id, job_id = _scene(
        world, upload, "Owned scene", stopped=False, created_by=guest, owner_user_id=guest.user_id
    )

    assert world.registry.get_job_owner_user_id(job_id) == guest.user_id
    world.registry.transition_job(job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    world.registry.transition_job(
        job_id,
        TransitionRequest(
            target_status=JobStatus.FAILED,
            error=ExecutionError(
                stage_id=StageId.INPUT_VALIDATE,
                error_code="PREVIEW_RUNNER_FAILED",
                human_message="Fixture failure",
                retryable=True,
                details={"exception_type": "TimeoutError"},
            ),
        ),
    )
    world.registry.transition_job(
        job_id,
        TransitionRequest(target_status=JobStatus.QUEUED),
        requested_by=editor,
    )
    world.registry.transition_job(job_id, TransitionRequest(target_status=JobStatus.CANCELLED))
    assert world.registry.get_job_owner_user_id(job_id) == guest.user_id

    entry = apply_deletion(
        world.context,
        DeletionRequest(project_ids=[project_id]),
        guest_owner_user_id=guest.user_id,
    ).entry_id
    restore_deletion(world.context, entry, guest_owner_user_id=guest.user_id)

    assert world.registry.get_project(project_id).created_by == guest
    assert world.registry.get_job_owner_user_id(job_id) == guest.user_id


def test_guest_cannot_delete_owned_project_with_foreign_upload_without_side_effects(world: SimpleNamespace) -> None:
    guest = Actor(user_id="guest-1", display_name="Guest One", role="guest")
    editor = Actor(user_id="editor-1", display_name="Editor One", role="editor")
    upload = _upload(world, uploaded_by=editor)
    project_id, _ = _scene(world, upload, "Guest project", created_by=guest, owner_user_id=guest.user_id)
    before_rows, before_files = _rows(world), _files(world)

    with pytest.raises(GuestOwnershipError, match="owner không khớp"):
        apply_deletion(
            world.context,
            DeletionRequest(project_ids=[project_id]),
            guest_owner_user_id=guest.user_id,
        )

    assert (_rows(world), _files(world)) == (before_rows, before_files)
    assert _in_trash(world) == []


def test_project_owner_cannot_change_during_persistence_cas(world: SimpleNamespace) -> None:
    guest = Actor(user_id="guest-1", display_name="Guest One", role="guest")
    editor = Actor(user_id="editor-1", display_name="Editor One", role="editor")
    upload = _upload(world, uploaded_by=guest)
    project_id, _ = _scene(world, upload, "Guest project", created_by=guest, owner_user_id=guest.user_id)
    project = world.registry.get_project(project_id)
    changed_owner = project.model_copy(update={"created_by": editor})
    assert world.registry.persistence is not None

    with pytest.raises(ValueError, match="creator"):
        world.registry.persistence.save_project(changed_owner, expected=project)

    assert world.registry.get_project(project_id).created_by == guest


def test_guest_cannot_delete_foreign_job_in_their_project(world: SimpleNamespace) -> None:
    guest = Actor(user_id="guest-1", display_name="Guest One", role="guest")
    upload = _upload(world, uploaded_by=guest)
    project_id, _ = _scene(world, upload, "Guest project", created_by=guest, owner_user_id=guest.user_id)
    editor = Actor(user_id="editor-1", display_name="Editor One", role="editor")
    foreign_job = world.registry.create_job(
        JobCreateInput(project_id=project_id), requested_by=editor, owner_user_id=editor.user_id
    )
    world.registry.transition_job(foreign_job.job_id, TransitionRequest(target_status=JobStatus.CANCELLED))
    before_rows, before_files = _rows(world), _files(world)

    with pytest.raises(GuestOwnershipError, match="owner không khớp"):
        apply_deletion(
            world.context,
            DeletionRequest(project_ids=[project_id]),
            guest_owner_user_id=guest.user_id,
        )

    assert (_rows(world), _files(world)) == (before_rows, before_files)
    assert _in_trash(world) == []


def test_delete_removes_the_scene_everywhere_and_leaves_other_scenes_alone(world: SimpleNamespace) -> None:
    project_id, job_id = _scene(world, _upload(world), "Gỡ")
    other_project, other_job = _scene(world, _upload(world, "other.mp4"), "Giữ")
    kept_files = {name: digest for name, digest in _files(world).items() if other_job in name or other_project in name}

    entry = _delete(world, project_ids=[project_id])

    with pytest.raises(ProjectNotFoundError):
        world.registry.get_project(project_id)
    with pytest.raises(JobNotFoundError):
        world.registry.get_job(job_id)
    assert [project.project_id for project in world.registry.list_projects()] == [other_project]
    assert world.registry.persistence.job_ids_after() == [other_job]
    assert [upload.original_name for upload in world.uploads.list()] == ["other.mp4"]
    assert not any(job_id in name or project_id in name for name in _files(world))
    assert {name: digest for name, digest in _files(world).items() if name in kept_files} == kept_files
    assert world.registry.get_job(other_job).status == JobStatus.CANCELLED

    record = get_trash_entry(world.database, entry)
    assert record.deleted_by is None and [line.name for line in record.plan.summary][0] == "Gỡ"
    for moved in (f"artifact/{job_id}", f"artifact/{project_id}", f"worker/{job_id}", f"rerun/{job_id}.rrd"):
        assert (world.trash / entry / moved).exists()
    audit = AuthService(world.database).recent_audit()
    assert {(row.action, row.target, row.user_id) for row in audit} >= {("scene.delete", project_id, None)}
    assert all(row.details["trash_entry"] == entry for row in audit if row.action.endswith(".delete"))


def test_shared_upload_is_kept_until_its_last_scene_goes(world: SimpleNamespace) -> None:
    upload = _upload(world)
    first, _ = _scene(world, upload, "Một")
    second, second_job = _scene(world, upload, "Hai")

    _delete(world, project_ids=[first])

    assert world.uploads.get(upload.upload_id).project_ids == [second]
    assert world.registry.runtime_resolver.require_uri(upload.artifact_uri, upload.checksum).is_file()
    assert world.registry.get_job(second_job).job_id == second_job

    _delete(world, project_ids=[second])

    assert world.uploads.list() == []
    assert not (world.root / "artifacts" / "jobs" / upload.upload_id).exists()


def test_restore_brings_back_exactly_what_was_removed(world: SimpleNamespace) -> None:
    shared = _upload(world)
    project_id, job_id = _scene(world, shared, "Gỡ rồi khôi phục")
    _scene(world, shared, "Dùng chung upload")
    own_project, _ = _scene(world, _upload(world, "own.mp4"), "Upload riêng")
    with world.database.transaction(write=True) as tx:
        tx.execute("INSERT INTO r2s_scene_requests(job_id,status,payload) VALUES (?,?,?)", (job_id, "done", "{}"))
    rows, files = _rows(world), _files(world)

    entry = _delete(world, project_ids=[project_id, own_project])
    assert _rows(world) != rows and _files(world) != files
    restore_deletion(world.context, entry, "user-1")

    assert (_rows(world), _files(world)) == (rows, files)
    assert world.registry.get_job(job_id).status == JobStatus.CANCELLED
    assert _in_trash(world) == [] and not (world.trash / entry).exists()
    actions = [row.action for row in AuthService(world.database).recent_audit()]
    assert actions.count("scene.restore") == 2 and actions.count("upload.restore") == 1
    assert {row.user_id for row in AuthService(world.database).recent_audit() if row.action == "scene.restore"} == {
        "user-1"
    }
    with pytest.raises(DeletionRefusedError, match="không có trong thùng rác"):
        restore_deletion(world.context, entry)


def test_scene_head_and_repair_rows_roundtrip_through_trash(world: SimpleNamespace) -> None:
    project_id, job_id = _scene(world, _upload(world), "Head restore")
    revision = world.registry.scene.publish_initial(job_id, world.registry.scene._fixture_scene())
    repository = SceneHeadRepository(world.database)
    head = repository.get(job_id)
    assert head is not None and head.scene_revision == "rev-001"
    item = SceneHeadBackfillItem.from_revision(revision)
    repair = SceneHeadRepairRecord.start(job_id, sha256_bytes(revision.scene_reference.artifact_uri.encode()), 1)
    repair_draft = repair.model_copy(
        update={
            "status": "COMPLETE",
            "phase": "RECHECK",
            "verified_count": 1,
            "rechecked_count": 1,
            "repair_checksum": "sha256:" + "0" * 64,
        }
    )
    completed_repair = repair_draft.model_copy(
        update={"repair_checksum": canonical_content_checksum(repair_draft, "repair_checksum")}
    )
    with world.database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_scene_head_repairs(job_id,status,generation,repair_checksum,payload) VALUES (?,?,?,?,?)",
            (
                job_id,
                completed_repair.status,
                completed_repair.generation,
                completed_repair.repair_checksum,
                completed_repair.model_dump_json(),
            ),
        )
        tx.execute(
            "INSERT INTO r2s_scene_head_backfill_items(job_id,scene_revision,item_checksum,payload) VALUES (?,?,?,?)",
            (job_id, item.scene_revision, item.item_checksum, item.model_dump_json()),
        )
    before = _rows(world)
    artifacts_before = _files(world)

    entry = _delete(world, project_ids=[project_id])
    assert _rows(world) != before
    restore_deletion(world.context, entry, "user-1")

    assert _rows(world) == before
    assert _files(world) == artifacts_before
    restored = repository.get(job_id)
    assert restored == head
    assert repository.get_repair(job_id) == completed_repair


def test_scene_deletion_refuses_in_progress_backfill_and_pending_publication(world: SimpleNamespace) -> None:
    project_id, job_id = _scene(world, _upload(world), "Active head operation")
    with world.database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_scene_head_repairs(job_id,status,generation,repair_checksum,payload) VALUES (?,?,?,?,?)",
            (job_id, "IN_PROGRESS", 1, "sha256:" + "a" * 64, "{}"),
        )

    with pytest.raises(DeletionRefusedError, match="backfill"):
        _delete(world, project_ids=[project_id])

    with world.database.transaction(write=True) as tx:
        tx.execute("DELETE FROM r2s_scene_head_repairs WHERE job_id=?", (job_id,))
        tx.execute(
            "INSERT INTO r2s_scene_publications(job_id,expected_generation,target_revision,lease_expires_at,payload) "
            "VALUES (?,?,?,?,?)",
            (job_id, 1, "rev-002", "2026-10-08T00:00:00+00:00", "{}"),
        )

    with pytest.raises(DeletionRefusedError, match="publication"):
        _delete(world, project_ids=[project_id])


def test_aborted_scene_publication_is_retained_but_does_not_block_trash_restore(world: SimpleNamespace) -> None:
    project_id, job_id = _scene(world, _upload(world), "Aborted publication")
    repository = SceneHeadRepository(world.database)
    reservation = repository.reserve_publication(job_id, None, "publish_initial", writer_id="failed-writer")
    assert repository.abort_publication(reservation)
    before = _rows(world)

    entry = _delete(world, project_ids=[project_id])
    with world.database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_scene_publications WHERE job_id=?", (job_id,)).fetchone() == (0,)

    restore_deletion(world.context, entry, "user-1")
    assert _rows(world) == before
    restored = repository.get_publication(job_id)
    assert restored is not None and restored.status == "ABORTED"


def test_restore_keeps_scenes_linked_to_the_upload_after_the_deletion(world: SimpleNamespace) -> None:
    upload = _upload(world)
    first, _ = _scene(world, upload, "Một")
    second, _ = _scene(world, upload, "Hai")
    entry = _delete(world, project_ids=[first])
    third, _ = _scene(world, upload, "Ba")

    restore_deletion(world.context, entry)

    assert world.uploads.get(upload.upload_id).project_ids == [first, second, third]


def test_restore_puts_back_a_legacy_upload_payload_byte_for_byte(world: SimpleNamespace) -> None:
    """Record upload đời trước thiếu field mặc định; ghi lại qua model sẽ làm payload khác bytes."""
    upload = _upload(world)
    first, _ = _scene(world, upload, "Một")
    _scene(world, upload, "Hai")
    with world.database.transaction(write=True) as tx:
        payload = json.loads(tx.execute("SELECT payload FROM r2s_uploads").fetchone()[0])
        legacy = {key: value for key, value in payload.items() if key not in {"input_kind", "detection"}}
        tx.execute("UPDATE r2s_uploads SET payload=?", (json.dumps(legacy, separators=(",", ":")),))
    rows = _rows(world)

    entry = _delete(world, project_ids=[first])
    restore_deletion(world.context, entry)

    assert _rows(world) == rows


@pytest.mark.parametrize(
    ("target", "stage", "reason"),
    [
        (None, None, "QUEUED"),
        (JobStatus.RUNNING, StageId.CAMERA_POSE, "RUNNING ở ST-CAMERA-POSE"),
    ],
)
def test_scene_a_worker_may_still_touch_is_refused(
    world: SimpleNamespace, target: JobStatus | None, stage: StageId | None, reason: str
) -> None:
    project_id, job_id = _scene(world, _upload(world), "Đang chạy", stopped=False)
    if target is not None:
        world.registry.transition_job(job_id, TransitionRequest(target_status=target, current_stage=stage))
    _refused(world, reason, project_ids=[project_id])


def test_scene_waiting_for_the_user_can_be_deleted(world: SimpleNamespace) -> None:
    project_id, job_id = _scene(world, _upload(world), "Chờ xác nhận tỉ lệ", stopped=False)
    waiting = TransitionRequest(target_status=JobStatus.RUNNING, current_stage=StageId.METRIC_CANONICALIZE)
    world.registry.transition_job(job_id, waiting)

    _delete(world, project_ids=[project_id])

    assert world.registry.list_projects() == []


def test_scene_with_a_pending_object_request_is_refused(world: SimpleNamespace) -> None:
    project_id, job_id = _scene(world, _upload(world), "Đang tách vật")
    with world.database.transaction(write=True) as tx:
        tx.execute("INSERT INTO r2s_scene_requests(job_id,status,payload) VALUES (?,?,?)", (job_id, "queued", "{}"))
    _refused(world, "dựng lại vật thể", project_ids=[project_id])


def test_released_scene_needs_explicit_permission(world: SimpleNamespace) -> None:
    project_id, job_id = _scene(world, _upload(world), "Đã phát hành")
    release = world.root / "artifacts" / "jobs" / job_id / "release" / "abc"
    release.mkdir(parents=True)
    (release / "release_manifest.json").write_text("{}")

    _refused(world, "US-06", project_ids=[project_id])
    _delete(world, project_ids=[project_id], allow_released=True)

    assert world.registry.list_projects() == []


def test_unknown_or_empty_requests_are_refused(world: SimpleNamespace) -> None:
    project_id, _ = _scene(world, _upload(world), "Có thật")
    _refused(world, "chưa nêu")
    _refused(world, "project-khong-co: không tìm thấy scene", project_ids=[project_id, "project-khong-co"])
    _refused(world, "không tìm thấy scene nhập", import_ids=["import-khong-co"])
    _refused(world, "không tìm thấy upload", upload_ids=["upload-khong-co"])


def test_upload_still_in_use_cannot_be_removed_on_its_own(world: SimpleNamespace) -> None:
    upload = _upload(world)
    project_id, _ = _scene(world, upload, "Đang dùng upload")
    _refused(world, f"còn được dùng bởi {project_id}", upload_ids=[upload.upload_id])


def test_orphan_upload_and_its_session_are_removed_and_restored(world: SimpleNamespace) -> None:
    upload = _upload(world, "big-test.mp4")
    with world.database.transaction(write=True) as tx:
        tx.execute("INSERT INTO r2s_upload_sessions(upload_id,payload) VALUES (?,?)", (upload.upload_id, "{}"))
    rows = _rows(world)

    entry = _delete(world, upload_ids=[upload.upload_id])

    assert _rows(world)["r2s_uploads"] == [] and _rows(world)["r2s_upload_sessions"] == []
    restore_deletion(world.context, entry)
    assert _rows(world) == rows


def test_imports_are_removed_and_share_uploads_like_scenes(world: SimpleNamespace) -> None:
    upload = _upload(world, "scene.ply", _gaussian(count=4))
    first = _import(world, upload, "Bản nhập 1")
    second = _import(world, upload, "Bản nhập 2")

    _delete(world, import_ids=[first])

    assert [item.import_id for item in world.imports.list()] == [second]
    assert world.uploads.get(upload.upload_id).upload_id == upload.upload_id
    assert world.imports.content_path(second).is_file()

    _delete(world, import_ids=[second])

    assert world.imports.list() == [] and world.uploads.list() == []


def test_import_being_packaged_is_refused(world: SimpleNamespace) -> None:
    upload = _upload(world, "scene.ply", _gaussian(count=4))
    record = world.imports.create(upload, "Đang đóng gói", None)
    _refused(world, "đang được đóng gói", import_ids=[record.import_id])


def test_remote_file_store_objects_survive_delete_and_go_on_purge(world: SimpleNamespace) -> None:
    project_id, job_id = _scene(world, _upload(world), "Kho R2")
    kept_project, kept_job = _scene(world, _upload(world, "keep.mp4"), "Giữ")
    store = MemoryObjectStore()
    world.context.resolver.remote = ArtifactRemote(store, "studio")
    try:
        for namespace in (project_id, job_id, kept_project, kept_job):
            world.context.resolver.sync_up(namespace)
        before = set(store.objects)
        gone = {key for key in before if f"/{project_id}/" in key or f"/{job_id}/" in key}
        assert gone and gone != before

        entry = _delete(world, project_ids=[project_id])
        assert set(store.objects) == before  # gỡ chưa đụng kho file: restore không phải tải lại

        result = purge_deletion(world.context, entry)
    finally:
        world.context.resolver.remote = None

    upload_keys = {key for key in before - set(store.objects)}
    assert upload_keys == gone
    assert result.remote_objects == len(gone) and result.local_bytes > 0
    assert world.registry.get_job(kept_job).project_id == kept_project


def test_restore_on_a_remote_deployment_works_without_the_local_cache(world: SimpleNamespace) -> None:
    """Đĩa của API trên cloud không bền: thư mục thùng rác mất thì file vẫn nằm trên kho, khôi phục vẫn phải được."""
    project_id, job_id = _scene(world, _upload(world), "Khôi phục trên R2")
    store = MemoryObjectStore()
    world.context.resolver.remote = ArtifactRemote(store)
    try:
        for namespace in (project_id, job_id):
            world.context.resolver.sync_up(namespace)
        before = set(store.objects)
        entry = _delete(world, project_ids=[project_id])
        shutil.rmtree(world.trash / entry)
        restore_deletion(world.context, entry)
        assert set(store.objects) == before
        assert world.registry.get_job(job_id).job_id == job_id
    finally:
        world.context.resolver.remote = None


def test_failed_transaction_leaves_no_trace(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    project_id, _ = _scene(world, _upload(world), "Lỗi giữa chừng")
    rows, files = _rows(world), _files(world)

    def conflict(*_: object) -> None:
        raise RuntimeStateConflictError("đổi giữa chừng")

    monkeypatch.setattr(deletion, "_audit", conflict)
    with pytest.raises(RuntimeStateConflictError):
        _delete(world, project_ids=[project_id])

    assert (_rows(world), _files(world)) == (rows, files)
    assert _in_trash(world) == [] and not world.trash.exists()


def test_delete_interrupted_while_moving_files_can_be_restored(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id, job_id = _scene(world, _upload(world), "Dừng khi đang chuyển")
    rows, files = _rows(world), _files(world)
    real_move = deletion.shutil.move
    calls: list[str] = []

    def move_once_then_fail(source: str, target: str) -> None:
        if calls:
            raise OSError("đĩa lỗi")
        calls.append(source)
        real_move(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(deletion.shutil, "move", move_once_then_fail)
        with pytest.raises(OSError, match="đĩa lỗi"):
            _delete(world, project_ids=[project_id])

    (entry,) = _in_trash(world)
    with pytest.raises(JobNotFoundError):
        world.registry.get_job(job_id)

    restore_deletion(world.context, entry)

    assert (_rows(world), _files(world)) == (rows, files)


def test_restore_never_overwrites_data_in_the_live_location(world: SimpleNamespace) -> None:
    project_id, job_id = _scene(world, _upload(world), "Bị chiếm chỗ")
    entry = _delete(world, project_ids=[project_id])
    occupied = world.root / "artifacts" / "jobs" / job_id
    occupied.mkdir(parents=True)
    (occupied / "other.txt").write_text("khác")
    folder = world.trash / entry
    trashed = sorted(str(path.relative_to(folder)) for path in folder.rglob("*"))

    with pytest.raises(DeletionRefusedError, match="đã có dữ liệu khác"):
        restore_deletion(world.context, entry)

    assert sorted(str(path.relative_to(folder)) for path in folder.rglob("*")) == trashed
    assert world.registry.list_projects() == [] and _in_trash(world) == [entry]
    assert (occupied / "other.txt").read_text() == "khác"


def test_purge_removes_the_entry_for_good_and_nothing_else(world: SimpleNamespace) -> None:
    project_id, _ = _scene(world, _upload(world), "Xoá hẳn")
    kept_project, kept_job = _scene(world, _upload(world, "keep.mp4"), "Giữ")
    other = _delete(world, project_ids=[kept_project])
    entry = _delete(world, project_ids=[project_id])
    rows = _rows(world)

    result = purge_deletion(world.context, entry, "user-9")

    assert result.local_bytes > 0 and result.remote_objects == 0
    assert not (world.trash / entry).exists() and _in_trash(world) == [other]
    assert _rows(world) == rows
    with pytest.raises(DeletionRefusedError, match="không có trong thùng rác"):
        restore_deletion(world.context, entry)
    with pytest.raises(DeletionRefusedError, match="không có trong thùng rác"):
        purge_deletion(world.context, entry)
    audit = AuthService(world.database).recent_audit()
    assert ("scene.purge", project_id, "user-9") in {(row.action, row.target, row.user_id) for row in audit}
    restore_deletion(world.context, other)
    assert world.registry.get_job(kept_job).project_id == kept_project


def test_entries_older_than_the_retention_are_purged_and_newer_ones_kept(world: SimpleNamespace) -> None:
    old_project, _ = _scene(world, _upload(world), "Quá hạn")
    new_project, new_job = _scene(world, _upload(world, "new.mp4"), "Còn hạn")
    old_entry = _delete(world, project_ids=[old_project])
    new_entry = _delete(world, project_ids=[new_project])
    context = replace(world.context, retention_days=7)
    created = get_trash_entry(world.database, old_entry).created_at

    assert purge_expired(world.context, created + timedelta(days=400)) == []  # tắt tự xoá thì không đụng gì
    assert purge_expired(context, created + timedelta(days=6, hours=23)) == []
    assert _in_trash(world) == [new_entry, old_entry] or _in_trash(world) == [old_entry, new_entry]
    with world.database.transaction(write=True) as tx:
        aged = get_trash_entry(world.database, old_entry).model_copy(update={"created_at": created - timedelta(days=8)})
        tx.execute("UPDATE r2s_trash SET payload=? WHERE entry_id=?", (aged.model_dump_json(), old_entry))

    assert purge_expired(context, datetime.now(UTC)) == [old_entry]

    assert _in_trash(world) == [new_entry] and not (world.trash / old_entry).exists()
    audit = AuthService(world.database).recent_audit()
    assert ("scene.purge", old_project, None) in {(row.action, row.target, row.user_id) for row in audit}
    restore_deletion(world.context, new_entry)
    assert world.registry.get_job(new_job).project_id == new_project


def test_entry_ids_cannot_escape_the_trash_folder(world: SimpleNamespace) -> None:
    with pytest.raises(DeletionRefusedError):
        purge_deletion(world.context, "../artifacts")
    with pytest.raises(DeletionRefusedError):
        restore_deletion(world.context, "../artifacts")


def test_legacy_file_based_entry_can_be_imported_then_restored(world: SimpleNamespace) -> None:
    """Lần gỡ của phiên bản trước giữ bản ghi dạng file trong thư mục; nhập vào thì dùng như mục thường."""
    project_id, job_id = _scene(world, _upload(world), "Kiểu cũ")
    rows, files = _rows(world), _files(world)
    entry = _delete(world, project_ids=[project_id])
    record = get_trash_entry(world.database, entry)
    legacy = world.root / "elsewhere" / entry
    legacy.parent.mkdir()
    (world.trash / entry).rename(legacy)
    old_plan = record.plan.model_copy(update={"remote_namespaces": []})
    (legacy / RECORD_NAME).write_text(record.model_copy(update={"plan": old_plan}).model_dump_json())
    with world.database.transaction(write=True) as tx:
        tx.execute("DELETE FROM r2s_trash")

    imported = import_legacy_entry(world.context, legacy)

    assert _in_trash(world) == [entry] and job_id in imported.plan.remote_namespaces
    with pytest.raises(DeletionRefusedError, match="thiếu"):
        import_legacy_entry(world.context, world.root / "elsewhere")
    restore_deletion(world.context, entry)
    assert (_rows(world), _files(world)) == (rows, files)


def test_cli_plans_deletes_lists_restores_and_purges(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id, job_id = _scene(world, _upload(world), "Qua CLI")
    busy_project, _ = _scene(world, _upload(world, "busy.mp4"), "Đang chờ worker", stopped=False)
    settings = SimpleNamespace(
        database_url=f"sqlite:///{world.root / 'runtime.db'}",
        artifact_root=world.root / "artifacts",
        artifact_s3_bucket=None,
        product_worker_root=world.root / "workers",
        product_rerun_recording_dir=world.root / "rerun",
        product_trash_root=None,
        product_trash_retention_days=7,
    )
    monkeypatch.setattr(delete_cli, "get_settings", lambda: settings)
    rows, files = _rows(world), _files(world)

    assert delete_cli.main(["plan", "--project", project_id]) == 0
    assert "Sẽ gỡ: 1 scene, 1 upload" in capsys.readouterr().out
    assert delete_cli.main(["plan", "--project", busy_project]) == 1
    assert "QUEUED" in capsys.readouterr().err
    assert delete_cli.main(["delete", "--project", busy_project]) == 1
    assert "Từ chối" in capsys.readouterr().err
    assert (_rows(world), _files(world)) == (rows, files)

    assert delete_cli.main(["delete", "--project", project_id]) == 0
    (entry,) = _in_trash(world)
    assert "Đã gỡ: 1 scene, 1 upload" in capsys.readouterr().out
    assert (world.root / "trash" / entry).is_dir()
    with pytest.raises(JobNotFoundError):
        world.registry.get_job(job_id)
    assert delete_cli.main(["list"]) == 0
    assert entry in capsys.readouterr().out

    assert delete_cli.main(["restore", "--entry", entry]) == 0
    assert (_rows(world), _files(world)) == (rows, files)
    assert delete_cli.main(["delete", "--project", project_id]) == 0
    (entry,) = _in_trash(world)
    assert delete_cli.main(["purge", "--entry", entry]) == 0
    assert _in_trash(world) == []
    assert delete_cli.main(["purge", "--entry", entry]) == 1
