"""Gỡ scene khỏi Studio: DB và thư mục phải đi cùng nhau, khôi phục được, và từ chối khi chưa an toàn."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.manifests import JobStatus, StageId
from src.services.orchestration.artifacts import ArtifactRemote
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
    apply_deletion,
    load_record,
    plan_deletion,
    purge_deletion,
    restore_deletion,
)
from src.services.orchestration.projects.models import (
    DataOrigin,
    JobCreateInput,
    SourceRightsAttestation,
    UploadProjectInput,
)
from src.services.orchestration.projects.registry import ProjectRegistry
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
        context=DeletionContext(database, registry.runtime_resolver, tmp_path / "workers", tmp_path / "rerun"),
        trash=tmp_path / "trash",
    )


def _upload(world: SimpleNamespace, name: str = "walk.mp4", payload: bytes = MP4 + b"video") -> UploadRecord:
    pending = world.uploads.begin(name)
    pending.publication.write(payload)
    return world.uploads.finish(pending)


def _scene(world: SimpleNamespace, upload: UploadRecord, name: str, *, stopped: bool = True) -> tuple[str, str]:
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
    project = world.registry.create_project_from_upload(upload, request, "self_attested")
    world.uploads.link_project(upload.upload_id, project.project_id)
    job = world.registry.create_job(JobCreateInput(project_id=project.project_id))
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


def _delete(world: SimpleNamespace, **ids: list[str] | bool) -> Path:
    record = apply_deletion(world.context, DeletionRequest(**ids), world.trash)
    return world.trash / record.entry_id


def _refused(world: SimpleNamespace, match: str, **ids: list[str] | bool) -> None:
    """Yêu cầu bị từ chối thì không được đổi DB, file hay để lại thư mục thùng rác."""
    rows, files = _rows(world), _files(world)
    with pytest.raises(DeletionRefusedError, match=match):
        _delete(world, **ids)
    assert (_rows(world), _files(world)) == (rows, files)
    assert not world.trash.exists() or not list(world.trash.iterdir())


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

    assert load_record(entry).state == "removed"
    for moved in (f"artifact/{job_id}", f"artifact/{project_id}", f"worker/{job_id}", f"rerun/{job_id}.rrd"):
        assert (entry / moved).exists()
    audit = AuthService(world.database).recent_audit()
    assert {(row.action, row.target, row.user_id) for row in audit} >= {("scene.delete", project_id, None)}
    assert all(row.details["trash_entry"] == entry.name for row in audit if row.action.endswith(".delete"))


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
    record = restore_deletion(world.context, entry)

    assert record.state == "restored" and load_record(entry).state == "restored"
    assert (_rows(world), _files(world)) == (rows, files)
    assert world.registry.get_job(job_id).status == JobStatus.CANCELLED
    assert [path.name for path in entry.rglob("*") if path.is_file()] == [RECORD_NAME]
    actions = [row.action for row in AuthService(world.database).recent_audit()]
    assert actions.count("scene.restore") == 2 and actions.count("upload.restore") == 1
    with pytest.raises(DeletionRefusedError, match="đã khôi phục"):
        restore_deletion(world.context, entry)


def test_restore_keeps_scenes_linked_to_the_upload_after_the_deletion(world: SimpleNamespace) -> None:
    upload = _upload(world)
    first, _ = _scene(world, upload, "Một")
    second, _ = _scene(world, upload, "Hai")
    entry = _delete(world, project_ids=[first])
    third, _ = _scene(world, upload, "Ba")

    restore_deletion(world.context, entry)

    assert world.uploads.get(upload.upload_id).project_ids == [first, second, third]


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


def test_deployment_with_remote_file_store_is_refused(world: SimpleNamespace) -> None:
    project_id, _ = _scene(world, _upload(world), "Kho S3")
    world.context.resolver.remote = ArtifactRemote(MemoryObjectStore())
    try:
        _refused(world, "kho file S3", project_ids=[project_id])
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
    assert list(world.trash.iterdir()) == []


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

    (entry,) = world.trash.iterdir()
    assert load_record(entry).state == "planned"
    with pytest.raises(JobNotFoundError):
        world.registry.get_job(job_id)
    with pytest.raises(DeletionRefusedError, match="chưa hoàn tất"):
        purge_deletion(entry)

    restore_deletion(world.context, entry)

    assert (_rows(world), _files(world)) == (rows, files)


def test_restore_never_overwrites_data_in_the_live_location(world: SimpleNamespace) -> None:
    project_id, job_id = _scene(world, _upload(world), "Bị chiếm chỗ")
    entry = _delete(world, project_ids=[project_id])
    occupied = world.root / "artifacts" / "jobs" / job_id
    occupied.mkdir(parents=True)
    (occupied / "other.txt").write_text("khác")
    trashed = sorted(str(path.relative_to(entry)) for path in entry.rglob("*"))

    with pytest.raises(DeletionRefusedError, match="đã có dữ liệu khác"):
        restore_deletion(world.context, entry)

    assert sorted(str(path.relative_to(entry)) for path in entry.rglob("*")) == trashed
    assert world.registry.list_projects() == []
    assert (occupied / "other.txt").read_text() == "khác"


def test_purge_only_removes_a_finished_trash_entry(world: SimpleNamespace) -> None:
    project_id, _ = _scene(world, _upload(world), "Xoá hẳn")
    kept_project, kept_job = _scene(world, _upload(world, "keep.mp4"), "Giữ")
    entry = _delete(world, project_ids=[project_id])
    live = _files(world)
    stranger = world.root / "not-a-trash-entry"
    stranger.mkdir()
    (stranger / "data.txt").write_text("đừng xoá")

    with pytest.raises(DeletionRefusedError, match="không phải thư mục của một lần gỡ"):
        purge_deletion(stranger)
    assert purge_deletion(entry) > 0

    assert not entry.exists() and (stranger / "data.txt").is_file()
    assert _files(world) == live
    assert world.registry.get_job(kept_job).project_id == kept_project


def test_record_from_another_entry_is_not_accepted(world: SimpleNamespace) -> None:
    project_id, _ = _scene(world, _upload(world), "Sai thư mục")
    entry = _delete(world, project_ids=[project_id])
    renamed = entry.with_name("renamed")
    entry.rename(renamed)
    with pytest.raises(DeletionRefusedError, match="thuộc lần gỡ khác"):
        purge_deletion(renamed)
    assert (renamed / RECORD_NAME).is_file()


def test_cli_plans_deletes_restores_and_purges(
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
    output = capsys.readouterr().out
    (entry,) = (world.root / "trash").iterdir()
    assert "Đã gỡ: 1 scene, 1 upload" in output and str(entry) in output
    with pytest.raises(JobNotFoundError):
        world.registry.get_job(job_id)

    assert delete_cli.main(["restore", "--entry", str(entry)]) == 0
    assert (_rows(world), _files(world)) == (rows, files)
    assert delete_cli.main(["purge", "--entry", str(entry)]) == 0
    assert not entry.exists()
    assert delete_cli.main(["purge", "--entry", str(entry)]) == 1
