"""T-053: job manifests and scene head revisions are verified and parsed once per checksum."""

from pathlib import Path

import pytest

from src.models.contracts.manifests import JobStatus
from src.services.orchestration.jobs.models import TransitionRequest
from tests.test_orchestration.test_job_lease import _registry, _running_job


def test_get_job_parses_manifest_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _registry(tmp_path)
    job = _running_job(registry)
    resolver = registry.persistence.resolver
    loads: list[str] = []
    real = resolver.load_model
    monkeypatch.setattr(
        resolver, "load_model", lambda reference, model: loads.append(reference.artifact_uri) or real(reference, model)
    )
    assert registry.persistence.get_job(job.job_id) == registry.persistence.get_job(job.job_id)
    assert len(loads) <= 1


def test_job_revision_change_returns_new_manifest(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    job = _running_job(registry)
    registry.persistence.get_job(job.job_id)
    registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.CANCELLED))
    assert registry.persistence.get_job(job.job_id).status == JobStatus.CANCELLED
