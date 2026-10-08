"""Tests cho error_view: che log_excerpt theo 4 vai trò người dùng (AUD-27.S2)."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.api.studio.error_view import (
    filter_job_attempt_errors,
    filter_job_progress_errors,
    filter_manifest_errors,
    filter_stage_artifact_errors,
    filter_stage_progress_errors,
    visible_error,
)
from src.models.contracts.manifests import (
    ExecutionError,
    JobManifest,
    JobStatus,
    StageArtifact,
    StageId,
    StageStatus,
)
from src.services.orchestration.auth import AuthService, UserRecord
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.jobs.progress import JobProgress, StageProgress
from src.services.orchestration.projects import ProjectRegistry


def _sample_error() -> ExecutionError:
    return ExecutionError(
        stage_id=StageId.CAMERA_POSE,
        error_code="COLMAP_PROCESS_FAILED",
        human_message="COLMAP process failed with code 1",
        retryable=False,
        details={
            "action": "colmap point_triangulator",
            "log_excerpt": ["line 1 of internal log", "line 2 of internal log"],
            "diagnostics": {"no_initial_pair": 1},
        },
    )


def _user(role: str) -> UserRecord:
    return UserRecord(
        user_id=f"user-{role}",
        email=f"{role}@example.com",
        display_name=role.capitalize(),
        password_hash="hash",
        role=role,
        active=True,
        created_at=datetime.now(UTC),
    )


def test_visible_error_unit_four_roles() -> None:
    error = _sample_error()

    # 1. user=None (auth_required=False hoặc không đăng nhập trong local dev) -> giữ nguyên
    err_none = visible_error(error, None)
    assert err_none is not None
    assert err_none.details is not None
    assert "log_excerpt" in err_none.details
    assert err_none.details["action"] == "colmap point_triangulator"

    # 2. guest -> bị che log_excerpt, các key khác còn nguyên
    err_guest = visible_error(error, _user("guest"))
    assert err_guest is not None
    assert err_guest.details is not None
    assert "log_excerpt" not in err_guest.details
    assert err_guest.details["action"] == "colmap point_triangulator"
    assert err_guest.details["diagnostics"] == {"no_initial_pair": 1}

    # 3. editor -> bị che log_excerpt, các key khác còn nguyên
    err_editor = visible_error(error, _user("editor"))
    assert err_editor is not None
    assert err_editor.details is not None
    assert "log_excerpt" not in err_editor.details
    assert err_editor.details["action"] == "colmap point_triangulator"

    # 4. reviewer -> nhận nguyên log_excerpt
    err_reviewer = visible_error(error, _user("reviewer"))
    assert err_reviewer is not None
    assert err_reviewer.details is not None
    assert "log_excerpt" in err_reviewer.details
    assert err_reviewer.details["log_excerpt"] == ["line 1 of internal log", "line 2 of internal log"]

    # Biên: error=None -> None
    assert visible_error(None, _user("guest")) is None


def test_filters_on_models() -> None:
    error = _sample_error()
    guest = _user("guest")
    reviewer = _user("reviewer")

    # StageArtifact
    stage = StageArtifact(
        stage_id=StageId.CAMERA_POSE,
        status=StageStatus.FAILED,
        error=error,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    assert "log_excerpt" not in filter_stage_artifact_errors(stage, guest).error.details
    assert "log_excerpt" in filter_stage_artifact_errors(stage, reviewer).error.details

    registry = ProjectRegistry()
    registry.seed_from_fixtures()
    manifest = registry.get_job("job-fixture-001")
    assert isinstance(manifest, JobManifest)
    failed_manifest = manifest.model_copy(update={"stage_artifacts": [stage]})
    assert "log_excerpt" not in filter_manifest_errors(failed_manifest, guest).stage_artifacts[0].error.details

    # JobProgress & StageProgress
    stage_prog = StageProgress(stage_id=StageId.CAMERA_POSE, state="failed", error=error)
    job_prog = JobProgress(
        job_id="job-1",
        status=JobStatus.FAILED,
        current_stage=StageId.CAMERA_POSE,
        attempt=1,
        started_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        stages=[stage_prog],
        preview_ready=False,
        error=error,
    )
    filtered_prog_guest = filter_job_progress_errors(job_prog, guest)
    assert "log_excerpt" not in filtered_prog_guest.error.details
    assert "log_excerpt" not in filtered_prog_guest.stages[0].error.details
    assert filtered_prog_guest.error.details["action"] == "colmap point_triangulator"
    assert "log_excerpt" not in filter_stage_progress_errors(stage_prog, guest).error.details

    filtered_prog_reviewer = filter_job_progress_errors(job_prog, reviewer)
    assert "log_excerpt" in filtered_prog_reviewer.error.details
    assert "log_excerpt" in filtered_prog_reviewer.stages[0].error.details

    # JobAttemptRecord
    attempt = JobAttemptRecord(
        attempt=1,
        status=JobStatus.FAILED,
        current_stage=StageId.CAMERA_POSE,
        recorded_at=datetime.now(UTC),
        error=error,
    )
    assert "log_excerpt" not in filter_job_attempt_errors(attempt, guest).error.details
    assert "log_excerpt" in filter_job_attempt_errors(attempt, reviewer).error.details


@pytest.fixture
def auth_db(tmp_path: Path) -> tuple[RuntimeDatabase, AuthService]:
    db = RuntimeDatabase(f"sqlite:///{tmp_path / 'test_auth.db'}")
    auth = AuthService(db)
    return db, auth


@pytest_asyncio.fixture
async def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from src.api import auth as auth_module
    from src.api.product import deps as product_deps
    from src.api.studio import deps as studio_deps
    from src.main import app

    db_path = f"sqlite:///{tmp_path / 'runtime.db'}"
    settings = SimpleNamespace(
        artifact_s3_bucket=None,
        database_url=db_path,
        artifact_root=tmp_path / "artifacts",
        product_worker_root=tmp_path / "worker",
        product_geometry_gpu_index=None,
        product_upload_max_bytes=1024 * 1024,
        product_privacy_mode="self_attested",
        product_processing_config=Path(__file__).resolve().parents[2] / "configs/product/processing_presets_v1.json",
        product_input_runtime_registry=None,
        auth_required=True,
        auth_session_days=7,
        auth_invite_days=7,
    )
    probe = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry = ProjectRegistry(
        runtime_root=tmp_path / "artifacts",
        database=RuntimeDatabase(settings.database_url),
        execution_profile=ExecutionProfile(
            config_checksum=probe._fixture_config_checksum(),
            runtime_manifest_checksum=probe._fixture_runtime_checksum(),
            seed=7,
        ),
    )
    auth_srv = AuthService(registry.persistence.database, 7, 7)

    monkeypatch.setattr(studio_deps, "get_settings", lambda: settings)
    monkeypatch.setattr(studio_deps, "get_project_registry", lambda: registry)
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    monkeypatch.setattr(auth_module, "settings", lambda: settings)
    monkeypatch.setattr(auth_module, "auth_service", lambda: auth_srv)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield SimpleNamespace(
            client=ac,
            registry=registry,
            auth_service=auth_srv,
            settings=settings,
        )


@pytest.mark.asyncio
async def test_route_progress_and_jobs_hide_log_excerpt_for_non_reviewers(app_client) -> None:
    client = app_client.client
    auth_srv = app_client.auth_service
    registry = app_client.registry

    # Tạo user guest, editor, reviewer
    auth_srv.create_user("g@test.com", "Guest", "password1234", "guest")
    guest_session, _ = auth_srv.login("g@test.com", "password1234")

    auth_srv.create_user("e@test.com", "Editor", "password1234", "editor")
    editor_session, _ = auth_srv.login("e@test.com", "password1234")

    auth_srv.create_user("r@test.com", "Reviewer", "password1234", "reviewer")
    reviewer_session, _ = auth_srv.login("r@test.com", "password1234")

    # Seed fixtures có sẵn project-fixture-001 và job-fixture-001
    registry.seed_from_fixtures()
    job = registry.get_job("job-fixture-001")
    error = _sample_error()

    # Cập nhật manifest của job với stage_artifacts bị lỗi và lưu vào persistence
    stage_art = StageArtifact(
        stage_id=StageId.CAMERA_POSE,
        status=StageStatus.FAILED,
        error=error,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    from src.services.orchestration.artifacts import with_canonical_checksum

    updated_job = with_canonical_checksum(
        job.model_copy(
            update={
                "stage_artifacts": [stage_art],
                "status": JobStatus.FAILED,
                "current_stage": StageId.CAMERA_POSE,
            }
        ),
        "job_manifest_checksum",
    )
    ref = registry.lifecycle.store.publish_manifest(updated_job)
    history = registry.persistence.list_attempts(job.job_id)
    event = JobAttemptRecord(
        attempt=history[-1].attempt,
        status=JobStatus.FAILED,
        current_stage=StageId.CAMERA_POSE,
        recorded_at=datetime.now(UTC),
        job_manifest_uri=ref.artifact_uri,
        job_manifest_checksum=ref.artifact_checksum,
        error=error,
    )
    registry.persistence.save_job(updated_job, ref, event, expected=job)
    job = updated_job

    # 1. Guest request progress: log_excerpt bị che, action còn
    res_guest = await client.get(
        f"/api/v1/jobs/{job.job_id}/progress",
        cookies={"r2s_session": guest_session},
    )
    assert res_guest.status_code == 200
    p_guest = res_guest.json()
    assert p_guest["error"]["details"]["action"] == "colmap point_triangulator"
    assert "log_excerpt" not in p_guest["error"]["details"]
    assert "log_excerpt" not in p_guest["stages"][3]["error"]["details"]

    # 2. Editor request progress: log_excerpt bị che, action còn
    res_editor = await client.get(
        f"/api/v1/jobs/{job.job_id}/progress",
        cookies={"r2s_session": editor_session},
    )
    assert res_editor.status_code == 200
    p_editor = res_editor.json()
    assert "log_excerpt" not in p_editor["error"]["details"]

    # 3. Reviewer request progress: log_excerpt còn nguyên
    res_reviewer = await client.get(
        f"/api/v1/jobs/{job.job_id}/progress",
        cookies={"r2s_session": reviewer_session},
    )
    assert res_reviewer.status_code == 200
    p_reviewer = res_reviewer.json()
    assert p_reviewer["error"]["details"]["log_excerpt"] == ["line 1 of internal log", "line 2 of internal log"]

    # 4. Khi auth_required=False: nhận nguyên log_excerpt
    app_client.settings.auth_required = False
    res_no_auth = await client.get(f"/api/v1/jobs/{job.job_id}/progress")
    assert res_no_auth.status_code == 200
    p_no_auth = res_no_auth.json()
    assert p_no_auth["error"]["details"]["log_excerpt"] == ["line 1 of internal log", "line 2 of internal log"]

    manifest_routes = (
        (
            f"/api/v1/jobs/{job.job_id}",
            lambda body: next(sa["error"]["details"] for sa in body["stage_artifacts"] if sa.get("error")),
        ),
        (
            f"/api/v1/projects/{job.project_id}/jobs",
            lambda body: next(
                sa["error"]["details"]
                for j in body["jobs"]
                if j["job_id"] == job.job_id
                for sa in j["stage_artifacts"]
                if sa.get("error")
            ),
        ),
        (
            f"/api/v1/jobs/{job.job_id}/attempts",
            lambda body: next(event["error"]["details"] for event in body["attempts"] if event.get("error")),
        ),
    )
    app_client.settings.auth_required = True
    for role, session in (
        ("guest", guest_session),
        ("editor", editor_session),
        ("reviewer", reviewer_session),
    ):
        excerpt_visible = role == "reviewer"
        for route, get_details in manifest_routes:
            response = await client.get(route, cookies={"r2s_session": session})
            assert response.status_code == 200, response.text
            details = get_details(response.json())
            assert ("log_excerpt" in details) is excerpt_visible
            assert details["action"] == "colmap point_triangulator"

    app_client.settings.auth_required = False
    for route, get_details in manifest_routes:
        response = await client.get(route)
        assert response.status_code == 200, response.text
        assert "log_excerpt" in get_details(response.json())
