"""T-059: the scene list carries the same next-action kind as the scene page."""

from pathlib import Path

from src.models.contracts.manifests import ExecutionError, JobStatus, StageId
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry


def _registry(tmp_path: Path) -> ProjectRegistry:
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    return registry


def test_scene_list_next_action_kinds(tmp_path: Path) -> None:
    from src.api.studio import scenes

    registry = _registry(tmp_path)
    queued = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    assert scenes._list_next_action(registry, queued, False, False, False) == "wait_system"

    running = registry.transition_job(queued.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    assert scenes._list_next_action(registry, running, False, True, False) == "review_anonymization"

    error = ExecutionError(error_code="COLMAP_TIMEOUT", stage_id=StageId.CAMERA_POSE, human_message="x", retryable=True)
    failed = registry.transition_job(queued.job_id, TransitionRequest(target_status=JobStatus.FAILED, error=error))
    assert scenes._list_next_action(registry, failed, False, False, False) == "retry_job"

    done = registry.get_job("job-fixture-001")
    if done.status == JobStatus.SUCCEEDED:
        assert scenes._list_next_action(registry, done, True, False, False) in {"scene_ready", "review_objects"}
