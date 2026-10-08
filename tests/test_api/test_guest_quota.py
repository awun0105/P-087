"""Guest quota acceptance at the HTTP boundary and upload-to-job transaction."""

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.models.contracts.manifests import ExecutionError, JobStatus, StageId
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.auth import AuthService, actor_of
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.profile import ExecutionProfile
from src.services.orchestration.projects.models import JobCreateInput, UploadProjectInput
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.uploads import VideoUploadService
from src.services.orchestration.uploads.models import UploadRecord

ATTESTATION = {
    "data_origin": "self_collected_no_pii",
    "declared_owner": "Quota test",
    "declared_purpose": "Guest quota acceptance test",
    "rights_to_use_confirmed": True,
    "anonymization_confirmed": True,
    "retention_acknowledged": True,
}
VIDEO = b"\x00\x00\x00\x14ftypqt  " + b"test-video-payload"
PRESETS = Path(__file__).resolve().parents[2] / "configs/product/processing_presets_v1.json"


def _system(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, worker_profile: bool = False):
    from src.api import auth
    from src.api.product import deps as product_deps
    from src.api.studio import deps as studio_deps
    from src.main import app

    database_url = f"sqlite:///{tmp_path / 'guest-quota.db'}"
    artifact_root = tmp_path / "artifacts"
    database = RuntimeDatabase(database_url)
    service = AuthService(database)
    user = service.create_user(f"guest-{uuid4().hex}@example.com", "Guest Owner", "mat-khau-du-dai", "guest")
    probe = ProjectRegistry(runtime_root=artifact_root)
    profile = (
        ExecutionProfile(
            config_checksum=probe._fixture_config_checksum(),
            runtime_manifest_checksum=probe._fixture_runtime_checksum(),
            seed=7,
        )
        if worker_profile
        else None
    )
    registry = ProjectRegistry(
        runtime_root=artifact_root,
        database=database,
        execution_profile=profile,
    )
    settings = SimpleNamespace(
        database_url=database_url,
        artifact_root=artifact_root,
        artifact_s3_bucket=None,
        product_upload_max_bytes=2_000_000,
        product_privacy_mode="self_attested",
        product_processing_config=PRESETS,
        auth_required=True,
        auth_guest_signup_enabled=False,
        auth_session_days=7,
        auth_invite_days=7,
        auth_cookie_secure=False,
        app_env="test",
    )
    monkeypatch.setattr(auth, "auth_service", lambda: service)
    monkeypatch.setitem(app.dependency_overrides, auth.require_contributor, lambda: user)
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: registry)
    monkeypatch.setattr(studio_deps, "get_project_registry", lambda: registry)
    monkeypatch.setattr(studio_deps, "get_settings", lambda: settings)
    return SimpleNamespace(
        app=app, auth=auth, database=database, registry=registry, service=service, user=user, settings=settings
    )


def _dispatchable_project(registry: ProjectRegistry, user) -> str:
    upload_id = f"upload-{uuid4().hex[:12]}"
    checksum = "sha256:" + hashlib.sha256(b"source video").hexdigest()
    upload = UploadRecord(
        upload_id=upload_id,
        original_name="source.mp4",
        media_type="video/mp4",
        size_bytes=12,
        checksum=checksum,
        artifact_uri=f"artifact://jobs/{upload_id}/input/source.mp4",
        received_at=datetime.now(UTC),
        uploaded_by=actor_of(user),
    )
    request = UploadProjectInput.model_validate(
        {"upload_id": upload_id, "name": "Guest warehouse", "attestation": ATTESTATION}
    )
    project = registry.create_project_from_upload(upload, request, "self_attested", created_by=actor_of(user))
    return project.project_id


@pytest.mark.asyncio
async def test_guest_api_accepts_exactly_three_concurrent_jobs_and_replays_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = _system(tmp_path, monkeypatch, worker_profile=True)
    project_id = _dispatchable_project(system.registry, system.user)
    token, _ = system.service.login(system.user.email, "mat-khau-du-dai")

    async with AsyncClient(
        transport=ASGITransport(app=system.app), base_url="http://test", cookies={"r2s_session": token}
    ) as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    f"/api/v1/projects/{project_id}/jobs",
                    json={},
                    headers={"Idempotency-Key": f"parallel-{index}"},
                )
                for index in range(4)
            )
        )
        accepted_with_index = [
            (index, response) for index, response in enumerate(responses) if response.status_code == 201
        ]
        accepted = [response for _, response in accepted_with_index]
        rejected = [response for response in responses if response.status_code == 429]
        assert len(accepted) == 3, [(response.status_code, response.text) for response in responses]
        assert len(rejected) == 1
        detail = rejected[0].json()["detail"]
        assert detail["code"] == "guest_daily_job_quota_exceeded"
        assert detail["quota"]["used"] == 3 and detail["quota"]["remaining"] == 0

        original_index, original = accepted_with_index[0]
        original_key = f"parallel-{original_index}"
        # The first accepted request is looked up by its returned job ID; replay must not create another row.
        replay = await client.post(
            f"/api/v1/projects/{project_id}/jobs", json={}, headers={"Idempotency-Key": original_key}
        )
        assert replay.status_code == 201
        assert replay.json()["job_id"] == original.json()["job_id"]
        conflict = await client.post(
            f"/api/v1/projects/{project_id}/jobs",
            json={"scene_revision": "different-request"},
            headers={"Idempotency-Key": original_key},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "idempotency_key_conflict"

        from src.api.product import scene as scene_routes
        from src.services.orchestration.scene.objectify_queue import ObjectifyState

        monkeypatch.setattr(
            scene_routes.objectify_queue,
            "request",
            lambda *_args: ObjectifyState(
                status="queued",
                mode="objectify",
                base_revision="rev-001",
                requested_at=datetime.now(UTC),
                available=True,
            ),
        )
        objectify = await client.post(
            f"/api/v1/jobs/{original.json()['job_id']}/scene/objectify",
            json={"expected_scene_revision": "rev-001", "mode": "objectify"},
        )
        assert objectify.status_code == 202, objectify.text

        me = (await client.get("/api/v1/auth/me")).json()
        assert me["quota"]["used"] == 3 and me["quota"]["remaining"] == 0

    with system.database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_jobs WHERE project_id=?", (project_id,)).fetchone() == (3,)
        assert tx.execute(
            "SELECT COUNT(*) FROM r2s_quota_intents WHERE actor_user_id=?", (system.user.user_id,)
        ).fetchone() == (3,)


@pytest.mark.asyncio
async def test_guest_scene_from_upload_commits_project_link_job_and_quota_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = _system(tmp_path, monkeypatch, worker_profile=True)
    uploads = VideoUploadService(
        system.database,
        ArtifactResolver(system.settings.artifact_root),
        system.settings.product_upload_max_bytes,
    )
    created: list[tuple[UploadRecord, str]] = []
    for index in range(4):
        pending = uploads.begin(f"guest-{index}.mp4")
        pending.publication.write(VIDEO)
        upload = uploads.finish(pending, uploaded_by=actor_of(system.user))
        created.append((upload, f"scene-{index}"))

    async with AsyncClient(transport=ASGITransport(app=system.app), base_url="http://test") as client:
        accepted = []
        for upload, key in created[:3]:
            response = await client.post(
                "/api/v1/scenes/from-upload",
                json={"upload_id": upload.upload_id, "name": "Guest scene", "attestation": ATTESTATION},
                headers={"Idempotency-Key": key},
            )
            assert response.status_code == 201, response.text
            accepted.append(response.json())

        duplicate = await client.post(
            "/api/v1/scenes/from-upload",
            json={
                "upload_id": created[0][0].upload_id,
                "name": "Guest scene",
                "attestation": ATTESTATION,
            },
            headers={"Idempotency-Key": created[0][1]},
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["job"]["job_id"] == accepted[0]["job"]["job_id"]

        fourth_upload, fourth_key = created[3]
        exhausted = await client.post(
            "/api/v1/scenes/from-upload",
            json={"upload_id": fourth_upload.upload_id, "name": "Guest scene", "attestation": ATTESTATION},
            headers={"Idempotency-Key": fourth_key},
        )
        assert exhausted.status_code == 429, exhausted.text
        assert exhausted.json()["detail"]["code"] == "guest_daily_job_quota_exceeded"

    assert uploads.get(created[0][0].upload_id).project_ids == [accepted[0]["project"]["project_id"]]
    assert uploads.get(fourth_upload.upload_id).project_ids == []
    with system.database.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM r2s_projects").fetchone() == (3,)
        assert tx.execute("SELECT COUNT(*) FROM r2s_jobs").fetchone() == (3,)
        assert tx.execute("SELECT used_count FROM r2s_guest_quota_windows").fetchone() == (3,)


@pytest.mark.asyncio
async def test_guest_manual_retry_counts_once_and_replays_accepted_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = _system(tmp_path, monkeypatch, worker_profile=True)
    project_id = _dispatchable_project(system.registry, system.user)
    token, _ = system.service.login(system.user.email, "mat-khau-du-dai")

    async with AsyncClient(
        transport=ASGITransport(app=system.app), base_url="http://test", cookies={"r2s_session": token}
    ) as client:
        created = await client.post(
            f"/api/v1/projects/{project_id}/jobs", json={}, headers={"Idempotency-Key": "retry-test-create"}
        )
        assert created.status_code == 201, created.text
        job_id = created.json()["job_id"]

        system.registry.transition_job(job_id, TransitionRequest(target_status=JobStatus.RUNNING))
        system.registry.transition_job(
            job_id,
            TransitionRequest(
                target_status=JobStatus.FAILED,
                error=ExecutionError(
                    stage_id=StageId.INPUT_VALIDATE,
                    error_code="PREVIEW_RUNNER_FAILED",
                    human_message="Transient fixture failure",
                    retryable=True,
                    details={"exception_type": "TimeoutError"},
                ),
            ),
        )

        first_retry = await client.post(
            f"/api/v1/jobs/{job_id}/retry", headers={"Idempotency-Key": "retry-test-manual"}
        )
        assert first_retry.status_code == 200, first_retry.text
        accepted_manifest = first_retry.json()
        assert accepted_manifest["status"] == JobStatus.QUEUED
        assert (await client.get("/api/v1/auth/me")).json()["quota"]["used"] == 2

        # Simulate worker progress before the client replays the accepted request.
        system.registry.transition_job(job_id, TransitionRequest(target_status=JobStatus.RUNNING))
        replay = await client.post(f"/api/v1/jobs/{job_id}/retry", headers={"Idempotency-Key": "retry-test-manual"})
        assert replay.status_code == 200, replay.text
        assert replay.json() == accepted_manifest
        assert system.registry.get_job(job_id).status == JobStatus.RUNNING

        second_job = await client.post(
            f"/api/v1/projects/{project_id}/jobs", json={}, headers={"Idempotency-Key": "retry-test-third"}
        )
        assert second_job.status_code == 201, second_job.text
        exhausted = await client.post(
            f"/api/v1/projects/{project_id}/jobs", json={}, headers={"Idempotency-Key": "retry-test-fourth"}
        )
        assert exhausted.status_code == 429
        detail = exhausted.json()["detail"]
        assert detail["code"] == "guest_daily_job_quota_exceeded"
        assert detail["quota"]["used"] == 3 and detail["quota"]["remaining"] == 0

    with system.database.transaction() as tx:
        assert tx.execute("SELECT used_count FROM r2s_guest_quota_windows").fetchone() == (3,)


@pytest.mark.asyncio
async def test_guest_run_requests_fail_closed_without_shared_runtime_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api.product import deps as product_deps

    system = _system(tmp_path, monkeypatch)
    in_memory_registry = ProjectRegistry(runtime_root=tmp_path / "volatile-artifacts")
    project_id = _dispatchable_project(in_memory_registry, system.user)
    job = in_memory_registry.create_job(
        JobCreateInput(project_id=project_id),
        requested_by=actor_of(system.user),
        owner_user_id=system.user.user_id,
    )
    monkeypatch.setattr(product_deps, "get_project_registry", lambda: in_memory_registry)
    token, _ = system.service.login(system.user.email, "mat-khau-du-dai")

    async with AsyncClient(
        transport=ASGITransport(app=system.app), base_url="http://test", cookies={"r2s_session": token}
    ) as client:
        create = await client.post(
            f"/api/v1/projects/{project_id}/jobs", json={}, headers={"Idempotency-Key": "no-db-create"}
        )
        retry = await client.post(f"/api/v1/jobs/{job.job_id}/retry", headers={"Idempotency-Key": "no-db-retry"})

    assert create.status_code == retry.status_code == 503
    assert create.json()["detail"] == retry.json()["detail"]
    assert system.service.guest_quota_summary(system.user.user_id).used == 0
