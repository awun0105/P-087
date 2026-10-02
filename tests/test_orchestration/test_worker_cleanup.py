"""Fixture proof cho cleanup boundary; không thay GPU/browser/runtime acceptance."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config import Settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs import runner
from src.services.orchestration.jobs.workspace import cleanup_attempt_workspace
from tests.test_orchestration.test_finalize_flow import _confirmed, _publish, _stage
from tests.test_orchestration.test_prepared_queue import _registry


def _workspace(tmp_path: Path) -> Path:
    """Scratch đúng namespace do runner tạo, gồm diagnostic file lồng nhau."""
    workspace = tmp_path / "workers" / "job-a" / ("attempt-" + "a" * 32)
    (workspace / "rec").mkdir(parents=True)
    (workspace / "rec" / "database.db").write_bytes(b"scratch")
    (workspace / "rec" / "process.log").write_text("diagnostic")
    (workspace / "preview.progress.jsonl").write_text("progress\n")
    (workspace / "preview.stdout.json").write_text("{}")
    return workspace


def test_cleanup_preserves_diagnostics_artifacts_resume_and_sibling(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    resume = workspace.parent / "resume" / "sparse.bin"
    resume.parent.mkdir()
    resume.write_bytes(b"resume")
    sibling = workspace.parent / ("attempt-" + "b" * 32)
    sibling.mkdir()
    (sibling / "database.db").write_bytes(b"active")
    resolver = ArtifactResolver(tmp_path / "artifacts")
    payload = b"published bytes"
    ref = ProductArtifactRef(
        schema_version="1.0",
        artifact_type="TestArtifact",
        artifact_uri="artifact://jobs/job-a/output.bin",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage="test",
        job_id="job-a",
    )
    FilesystemArtifactStore(resolver).publish(ref, payload)
    result = cleanup_attempt_workspace(
        workspace, worker_root=tmp_path / "workers", artifact_root=resolver.artifact_root
    )
    assert result.files_removed == 1 and result.bytes_removed == 7 and result.errors == 0
    assert not (workspace / "rec" / "database.db").exists()
    assert (workspace / "rec" / "process.log").read_text() == "diagnostic"
    assert (workspace / "preview.progress.jsonl").is_file()
    assert (workspace / "preview.stdout.json").is_file()
    assert resolver.require(ref).read_bytes() == payload  # Real resolver checksum proof après cleanup.
    assert resume.read_bytes() == b"resume" and (sibling / "database.db").read_bytes() == b"active"
    assert (
        cleanup_attempt_workspace(
            workspace, worker_root=tmp_path / "workers", artifact_root=resolver.artifact_root
        ).files_removed
        == 0
    )


@pytest.mark.parametrize("kind", ["outside", "root", "job", "resume", "overlap", "symlink"])
def test_cleanup_rejects_unsafe_roots(tmp_path: Path, kind: str) -> None:
    workspace = _workspace(tmp_path)
    worker_root, artifacts = tmp_path / "workers", tmp_path / "artifacts"
    if kind == "outside":
        worker_root = tmp_path / "other"
    elif kind == "root":
        workspace = worker_root
    elif kind == "job":
        workspace = workspace.parent
    elif kind == "resume":
        workspace = workspace.parent / "resume"
    elif kind == "overlap":
        artifacts = workspace / "published"
    elif kind == "symlink":
        link = workspace.parent / ("finalize-" + "c" * 32)
        link.symlink_to(workspace, target_is_directory=True)
        workspace = link
    with pytest.raises(ValueError):
        cleanup_attempt_workspace(workspace, worker_root=worker_root, artifact_root=artifacts)
    assert list((tmp_path / "workers").rglob("database.db"))


def test_cleanup_does_not_follow_nested_symlink(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "model.bin").write_bytes(b"keep")
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    (workspace / "model.bin").symlink_to(outside / "model.bin")
    cleanup_attempt_workspace(workspace, worker_root=tmp_path / "workers", artifact_root=tmp_path / "artifacts")
    assert (outside / "model.bin").read_bytes() == b"keep"


@pytest.mark.parametrize("failure", [None, "receipt", "verify", "sync", "commit"])
def test_preview_cleanup_only_after_verified_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    workspace = _workspace(tmp_path)
    registry = _registry(tmp_path / "runtime")
    job = registry.get_job("job-fixture-001")
    reference = _publish(registry, job.job_id, "preview.json", "TestResult", runner.StageId.VISUAL_RECON)
    fake = Mock()
    fake.runtime_resolver = registry.runtime_resolver
    fake.record_preview.return_value = job  # Successful preview remains RUNNING in real reducer.
    if failure == "commit":
        fake.record_preview.side_effect = runner.RuntimeStateConflictError("stale")
    monkeypatch.setattr(
        runner,
        "_run_tool",
        lambda *args: (1 if failure == "receipt" else 0, {"result_ref": reference.model_dump(mode="json")}),
    )

    def verify(*args: object) -> SimpleNamespace:
        """Return exact request attempt id to exercise reducer/cleanup ordering."""
        if failure == "verify":
            raise ValueError("invalid")
        import json

        request = json.loads((workspace / "preview.request.json").read_text())
        return SimpleNamespace(attempt_id=request["attempt_id"], error="failed" if failure == "receipt" else None)

    monkeypatch.setattr(runner, "verify_prepared_preview", verify)
    monkeypatch.setattr(runner, "_record_benchmark", lambda *args: None)
    if failure == "sync":
        monkeypatch.setattr(registry.runtime_resolver, "sync_up", Mock(side_effect=OSError("sync")))
    settings = Settings(product_worker_root=tmp_path / "workers")
    attempt = runner._Attempt(fake, settings, job, workspace)
    profile = SimpleNamespace(colmap={}, brush={})
    if failure in {"verify", "sync", "commit"}:
        with pytest.raises((ValueError, OSError, runner.RuntimeStateConflictError)):
            runner._execute_preview(attempt, reference, profile)
    else:
        assert runner._execute_preview(attempt, reference, profile) == job
    assert (workspace / "rec" / "database.db").exists() == (failure is not None)
    assert registry.runtime_resolver.require(reference).is_file()


def test_keep_scratch_and_cleanup_io_failure_do_not_change_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace(tmp_path)
    registry = _registry(tmp_path / "runtime")
    attempt = runner._Attempt(
        registry,
        Settings(product_worker_root=tmp_path / "workers", product_worker_keep_scratch=True),
        registry.get_job("job-fixture-001"),
        workspace,
    )
    cleanup = Mock(side_effect=PermissionError("private path"))
    monkeypatch.setattr(runner, "cleanup_attempt_workspace", cleanup)
    runner._cleanup_attempt_workspace(attempt)
    cleanup.assert_not_called()
    attempt.settings.product_worker_keep_scratch = False
    before = attempt.job
    runner._cleanup_attempt_workspace(attempt)
    assert attempt.job == before and (workspace / "rec" / "database.db").is_file()


@pytest.mark.parametrize("failed", [False, True])
def test_finalize_consumes_scene_before_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed: bool) -> None:
    registry, job, confirmation = _confirmed(tmp_path / "runtime")
    reference = _publish(registry, job.job_id, "result.json", "RecFinalizeResult", runner.StageId.RGB_GEOMETRY)
    settings = Settings(product_worker_root=tmp_path / "workers")
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "get_project_registry", lambda: registry)
    monkeypatch.setattr(runner, "_authorized_decision", lambda *args: (confirmation, "sha256:" + "a" * 64))

    def tool(attempt: runner._Attempt, *args: object) -> tuple[int, dict]:
        """Fixture worker writes scratch that scene consumer needs."""
        (attempt.workspace / "model.bin").write_bytes(b"scratch")
        return int(failed), {"result_ref": reference.model_dump(mode="json")}

    monkeypatch.setattr(runner, "_run_tool", tool)

    def result(*args: object) -> SimpleNamespace:
        """Fixture receipt checked before real durable reducer invocation seam."""
        workspace = next((tmp_path / "workers" / job.job_id).glob("finalize-*"))
        return SimpleNamespace(attempt_id=workspace.name, error="failed" if failed else None, bundle_ref=reference)

    monkeypatch.setattr(runner, "load_finalize_result", result)

    def scene(attempt: runner._Attempt, workspace: Path, *args: object) -> list:
        assert (workspace / "model.bin").read_bytes() == b"scratch"
        return [_stage(reference, runner.StageId.OBJECT_EXTRACT)]

    monkeypatch.setattr(runner, "_extract_scene_stage", scene)
    monkeypatch.setattr(registry, "record_finalize", lambda *args: job)
    assert runner.run_finalize_job(job.job_id) == job
    scratch = list((tmp_path / "workers").rglob("model.bin"))
    assert bool(scratch) == failed
