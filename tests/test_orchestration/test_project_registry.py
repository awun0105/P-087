"""Unit tests for the product project/job registry.

Tests cover:
- Fixture seeding and project/job visibility
- Privacy gate enforcement on job creation
- Artifact data_class filtering (evaluation_only must never appear)
- Privacy report seam (record_privacy_report)
- Not-found errors
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.models.contracts.artifacts import ArtifactDataClass
from src.models.contracts.manifests import (
    JobStatus,
    PrivacyInspectionScope,
    PrivacyResult,
    PrivacyValidationReport,
    StageArtifact,
    StageStatus,
)
from src.services.orchestration.projects.errors import (
    JobNotFoundError,
    PrivacyGateBlockedError,
    ProjectNotFoundError,
)
from src.services.orchestration.projects.models import (
    DataOrigin,
    JobCreateInput,
    ProjectCreateInput,
    SourceRightsAttestation,
)
from src.services.orchestration.projects.registry import (
    ProjectRegistry,
    with_canonical_checksum,
)

_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def registry(tmp_path: Path) -> ProjectRegistry:
    """Fresh in-memory registry backed by the repo's shared fixtures.

    `runtime_root` phải là thư mục tạm: `create_job` ghi JobManifest xuống đĩa, và mặc định của registry là kho
    artifact thật của repo (`data/artifacts`).
    """
    instance = ProjectRegistry(_FIXTURE_ROOT, runtime_root=tmp_path / "artifacts")
    instance.seed_from_fixtures()
    return instance


@pytest.fixture
def create_input() -> ProjectCreateInput:
    return ProjectCreateInput(
        name="Test project",
        source_type="upload",
        input_manifest_checksum="sha256:" + "a" * 64,
        attestation=SourceRightsAttestation(
            data_origin=DataOrigin.ANONYMIZED,
            declared_owner="Cường",
            declared_purpose="Unit testing",
            rights_to_use_confirmed=True,
            anonymization_confirmed=True,
            retention_acknowledged=True,
        ),
    )


# ── fixture seeding ─────────────────────────────────────────────────────────


def test_fixture_project_loaded(registry: ProjectRegistry) -> None:
    projects = registry.list_projects()
    assert len(projects) == 1
    p = projects[0]
    assert p.project_id == "project-fixture-001"


def test_fixture_job_loaded(registry: ProjectRegistry) -> None:
    jobs = registry.list_jobs("project-fixture-001")
    assert len(jobs) == 1
    assert jobs[0].job_id == "job-fixture-001"
    assert jobs[0].status == JobStatus.SUCCEEDED


def test_fixture_privacy_is_verified_anonymized(registry: ProjectRegistry) -> None:
    p = registry.get_project("project-fixture-001")
    assert p.privacy_report.result == PrivacyResult.VERIFIED_ANONYMIZED


# ── project creation ─────────────────────────────────────────────────────────


def test_create_project_returns_preliminary_screened(registry: ProjectRegistry, create_input) -> None:
    record = registry.create_project(create_input)
    assert record.privacy_report.result == PrivacyResult.PRELIMINARY_SCREENED


def test_create_project_stores_attestation(registry: ProjectRegistry, create_input) -> None:
    record = registry.create_project(create_input)
    assert record.source_rights_attestation["declared_owner"] == "Cường"
    assert record.source_rights_attestation["anonymization_confirmed"] is True


def test_dataset_project_uses_images_as_input_and_keeps_display_video_separate(
    registry: ProjectRegistry, tmp_path: Path
) -> None:
    from src.models.contracts.manifests import InputManifest

    image_paths = (tmp_path / "000.jpg", tmp_path / "001.png")
    for index, path in enumerate(image_paths):
        path.write_bytes(f"image-{index}".encode())
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"display-only-video")
    project = registry.create_project_from_dataset_images(
        name="dataset test", dataset_owner="Mip-NeRF 360", images=image_paths, display_video=video
    )
    manifest = InputManifest.model_validate_json(
        registry.runtime_resolver.require(project.input_manifest_ref).read_bytes()
    )
    assert project.privacy_mode == "self_attested"
    assert project.display_video_ref is not None and project.input_video is None
    assert [item.original_name for item in manifest.files] == ["000.jpg", "001.png"]
    assert all(item.media_type.startswith("image/") for item in manifest.files)
    assert all("scene.mp4" not in item.artifact_uri for item in manifest.files)
    assert registry.runtime_resolver.require(project.display_video_ref).read_bytes() == b"display-only-video"
    assert registry.create_job(JobCreateInput(project_id=project.project_id)).status == JobStatus.QUEUED


def test_created_project_appears_in_list(registry: ProjectRegistry, create_input) -> None:
    record = registry.create_project(create_input)
    ids = [p.project_id for p in registry.list_projects()]
    assert record.project_id in ids


# ── privacy gate ─────────────────────────────────────────────────────────────


def test_create_job_blocked_when_preliminary(registry: ProjectRegistry, create_input) -> None:
    record = registry.create_project(create_input)
    with pytest.raises(PrivacyGateBlockedError):
        registry.create_job(JobCreateInput(project_id=record.project_id))


def test_create_job_allowed_on_fixture_project(registry: ProjectRegistry) -> None:
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    assert job.status == JobStatus.QUEUED
    assert job.project_id == "project-fixture-001"


def test_privacy_report_seam_enables_dispatch(registry: ProjectRegistry, create_input) -> None:
    """record_privacy_report is the only way to upgrade a new project's state."""
    record = registry.create_project(create_input)
    draft = PrivacyValidationReport(
        schema_version="1.0",
        input_manifest_checksum=record.input_manifest_checksum,
        inspection_scope=PrivacyInspectionScope.ALL_SELECTED_FRAMES,
        selected_frame_count=10,
        inspected_frame_count=10,
        unresolved_findings=[],
        result=PrivacyResult.VERIFIED_ANONYMIZED,
        report_checksum="sha256:" + "0" * 64,
    )
    report = with_canonical_checksum(draft, "report_checksum")
    registry.record_privacy_report(record.project_id, report)
    job = registry.create_job(JobCreateInput(project_id=record.project_id))
    assert job.status == JobStatus.QUEUED


def test_privacy_report_wrong_checksum_rejected(registry: ProjectRegistry, create_input) -> None:
    record = registry.create_project(create_input)
    wrong_checksum = "sha256:" + "b" * 64  # differs from record's input_manifest_checksum
    draft = PrivacyValidationReport(
        schema_version="1.0",
        input_manifest_checksum=wrong_checksum,
        inspection_scope=PrivacyInspectionScope.SAMPLED,
        selected_frame_count=0,
        inspected_frame_count=0,
        unresolved_findings=[],
        result=PrivacyResult.VERIFIED_ANONYMIZED,
        report_checksum="sha256:" + "0" * 64,
    )
    report = with_canonical_checksum(draft, "report_checksum")
    with pytest.raises(ValueError, match="input manifest"):
        registry.record_privacy_report(record.project_id, report)


# ── artifact filtering ────────────────────────────────────────────────────────


_GROUNDTRUTH_ON_DISK = (
    _FIXTURE_ROOT / "artifact_store" / "jobs" / "job-fixture-001" / "evaluation_only" / "groundtruth_map.mock"
)


def test_evaluation_only_artifacts_excluded(registry: ProjectRegistry) -> None:
    """evaluation_only data must never appear in the product artifact list.

    The ground-truth file really exists under the artifact root, so this fails if
    the registry ever enumerates the store instead of the typed stage artifacts.
    """
    assert _GROUNDTRUTH_ON_DISK.is_file(), "fixture ground truth must exist for this test to mean anything"
    visible, _ = registry.list_job_artifacts("job-fixture-001")
    uris = [a.artifact_uri for a in visible]
    assert not any("evaluation_only" in u for u in uris)
    assert not any("groundtruth" in u for u in uris)
    assert not any("ground_truth" in u for u in uris)


def test_stage_artifact_rejects_non_product_data_class() -> None:
    """The shared contract itself forbids ground_truth/evaluation_only stage refs."""
    with pytest.raises(ValidationError):
        StageArtifact(
            stage_id="ST-REVIEW",
            status=StageStatus.SUCCEEDED,
            artifact_type="GroundTruthMap",
            artifact_uri="artifact://jobs/job-fixture-001/evaluation_only/groundtruth_map.mock",
            artifact_checksum="sha256:" + "d" * 64,
            data_class=ArtifactDataClass.EVALUATION_ONLY,
            started_at="2026-09-22T00:00:00Z",
            completed_at="2026-09-22T00:00:01Z",
        )


def test_published_artifact_refs_resolve_and_verify(registry: ProjectRegistry) -> None:
    """Ref trả ra phải resolve được và khớp checksum byte, không chỉ là metadata.

    Đây là bằng chứng cho quy ước `artifact://jobs/<job_id>/<path>`: segment `jobs/`
    được thêm lại khi map xuống đĩa.
    """
    visible, _ = registry.list_job_artifacts("job-fixture-001")
    assert visible, "fixture job phải có ít nhất một artifact product"
    for ref in visible:
        assert registry.resolver.require(ref).is_file()


def test_artifact_uris_are_logical_not_filesystem(registry: ProjectRegistry) -> None:
    visible, _ = registry.list_job_artifacts("job-fixture-001")
    for ref in visible:
        assert ref.artifact_uri.startswith("artifact://jobs/")
        assert "\\" not in ref.artifact_uri


def test_artifact_data_class_is_product_visible(registry: ProjectRegistry) -> None:
    visible, _ = registry.list_job_artifacts("job-fixture-001")
    for ref in visible:
        assert ref.data_class in (ArtifactDataClass.PRODUCT_INPUT, ArtifactDataClass.DERIVED)


# ── not-found errors ──────────────────────────────────────────────────────────


def test_get_missing_project_raises(registry: ProjectRegistry) -> None:
    with pytest.raises(ProjectNotFoundError):
        registry.get_project("no-such-project")


def test_get_missing_job_raises(registry: ProjectRegistry) -> None:
    with pytest.raises(JobNotFoundError):
        registry.get_job("no-such-job")


def test_list_artifacts_for_missing_job_raises(registry: ProjectRegistry) -> None:
    with pytest.raises(JobNotFoundError):
        registry.list_job_artifacts("no-such-job")
