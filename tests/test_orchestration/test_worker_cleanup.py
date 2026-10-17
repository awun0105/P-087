"""Fixture proof cho cleanup boundary; không thay GPU/browser/runtime acceptance."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config import Settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.jobs import runner
from src.services.orchestration.jobs.workspace import (
    CleanupResult,
    attempt_in_use,
    attempt_lease,
    cleanup_attempt_workspace,
    cleanup_finished_job,
    reclaim_worker_scratch,
)
from tests.test_orchestration.test_finalize_flow import _confirmed, _publish, _stage
from tests.test_orchestration.test_prepared_queue import _registry
from tests.test_reconstruction.test_rec11_preview import preview


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


def test_preview_producer_outputs_resolve_after_scratch_cleanup(tmp_path: Path) -> None:
    """Real REC producer/store/consumer qua fixture tools; không manual conversion."""
    worker, request, resolver = preview(tmp_path)
    workspace = tmp_path / "workers" / request.job_id / ("attempt-" + "d" * 32)
    workspace.mkdir(parents=True)
    output, reference = worker.run(request, workspace / "rec")
    assert output.preview_complete
    result = cleanup_attempt_workspace(
        workspace, worker_root=tmp_path / "workers", artifact_root=resolver.artifact_root
    )
    receipt = runner.verify_prepared_preview(reference, resolver.require)
    assert result.files_removed > 0 and receipt.error is None
    assert receipt.preview_ref is not None and resolver.require(output.delivery_ref).read_bytes() == b"fixture SOG"


def test_cleanup_io_error_is_reported_without_removing_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    unlink = Path.unlink

    def deny(path: Path, *args: object, **kwargs: object) -> None:
        if path.name == "database.db":
            raise PermissionError("private path")
        unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny)
    result = cleanup_attempt_workspace(
        workspace, worker_root=tmp_path / "workers", artifact_root=tmp_path / "artifacts"
    )
    assert result.errors == 1 and result.files_removed == 0
    assert (workspace / "rec" / "database.db").is_file() and (workspace / "rec" / "process.log").is_file()


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
        return SimpleNamespace(
            attempt_id=request["attempt_id"], error="failed" if failure == "receipt" else None, preview_ref=None
        )

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
    if failure in {None, "receipt"}:
        verified_at = fake.record_preview.call_args.kwargs["verified_at"]
        assert (verified_at is not None) is (failure is None)
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
    monkeypatch.setattr(
        runner,
        "load_job_config",
        lambda *args: SimpleNamespace(
            geometry={
                "resolution_m": 0.1,
                "collision_mesh": "faces",
                "floor_fill_size_m": 1.2,
                "external_fill_size_m": 0,
            }
        ),
    )

    def tool(attempt: runner._Attempt, *args: object) -> tuple[int, dict]:
        """Fixture worker writes scratch that scene consumer needs."""
        request = json.loads((attempt.workspace / "finalize.request.json").read_bytes())
        assert request["geometry"]["resolution_m"] == 0.1
        assert request["geometry"]["collision_mesh"] == "faces"
        assert request["geometry"]["floor_fill_size_m"] == 1.2
        assert request["geometry"].get("external_fill_size_m") is None
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


def test_cleanup_works_when_worker_root_is_reached_through_a_symlink(tmp_path: Path) -> None:
    """Dữ liệu worker nằm trên ổ khác qua symlink: runner tạo workspace dưới đường dẫn đã giải."""
    real = tmp_path / "external-drive"
    (real / "workers").mkdir(parents=True)
    (tmp_path / "data").symlink_to(real, target_is_directory=True)
    configured = tmp_path / "data" / "workers"
    for root in (configured, tmp_path / "linked-root"):
        if root.name == "linked-root":
            root.symlink_to(real / "workers", target_is_directory=True)  # chính worker root là symlink
        workspace = root.resolve() / "job-a" / ("attempt-" + "e" * 32)  # như runner: resolve() rồi mới ghép
        (workspace / "rec").mkdir(parents=True, exist_ok=True)
        (workspace / "rec" / "database.db").write_bytes(b"scratch")
        result = cleanup_attempt_workspace(workspace, worker_root=root, artifact_root=tmp_path / "artifacts")
        assert result.files_removed == 1 and not (workspace / "rec" / "database.db").exists()
        # Workspace hết file thì bị gỡ luôn. Đường dẫn chưa giải của cùng workspace cũng được nhận.
        assert not workspace.exists()
        workspace.mkdir(parents=True)
        (workspace / "model.bin").write_bytes(b"x")
        unresolved = root / "job-a" / workspace.name
        assert cleanup_attempt_workspace(
            unresolved, worker_root=root, artifact_root=tmp_path / "artifacts"
        ).files_removed


def test_large_intermediate_text_is_scratch_but_logs_are_always_kept(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    megabyte = 1024 * 1024
    (workspace / "rec" / "points3D.txt").write_bytes(b"p" * (2 * megabyte))  # model COLMAP dạng text
    (workspace / "rec" / "transforms.json").write_bytes(b"t" * (2 * megabyte))
    (workspace / "rec" / "cameras.txt").write_text("small")
    (workspace / "rec" / "brush.log").write_bytes(b"l" * (2 * megabyte))
    cleanup_attempt_workspace(workspace, worker_root=tmp_path / "workers", artifact_root=tmp_path / "artifacts")
    left = {path.name for path in workspace.rglob("*") if path.is_file()}
    assert left == {"process.log", "preview.progress.jsonl", "preview.stdout.json", "cameras.txt", "brush.log"}


def test_lease_marks_attempt_in_use_until_runner_leaves(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    assert not attempt_in_use(workspace)
    with attempt_lease(workspace):
        assert attempt_in_use(workspace)
    assert not attempt_in_use(workspace)
    # Lease của tiến trình đã chết tự nhả; tiến trình đứng trong workspace (như Brush) cũng là "đang dùng".
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl,sys,time; h=open(sys.argv[1],'a'); fcntl.flock(h, fcntl.LOCK_EX); print('ok', flush=True);"
            " time.sleep(60)",
            str(workspace / "attempt.lock"),
        ],
        stdout=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == b"ok"
        assert attempt_in_use(workspace)
    finally:
        holder.kill()
        holder.wait()
    assert not attempt_in_use(workspace)
    inside = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=workspace / "rec")
    try:
        assert attempt_in_use(workspace)
    finally:
        inside.kill()
        inside.wait()
    assert not attempt_in_use(workspace)


def _job_with_history(tmp_path: Path, job_id: str = "job-a") -> tuple[Path, Path, Path]:
    """Job có một attempt cũ đã dừng, một attempt đang chạy (giữ lease) và thư mục resume."""
    root = tmp_path / "workers" / job_id
    old, active, resume = root / ("attempt-" + "1" * 32), root / ("finalize-" + "2" * 32), root / "resume"
    for directory in (old, active, resume / "colmap-key" / "sparse"):
        directory.mkdir(parents=True)
    (old / "database.db").write_bytes(b"old scratch")
    (old / "preview.stderr.log").write_text("why it failed")
    (active / "model.bin").write_bytes(b"active")
    (resume / "colmap-key" / "sparse" / "points3D.bin").write_bytes(b"sparse")
    return old, active, resume


def test_finished_job_drops_resume_and_idle_attempts_only(tmp_path: Path) -> None:
    old, active, resume = _job_with_history(tmp_path)
    roots = {"worker_root": tmp_path / "workers", "artifact_root": tmp_path / "artifacts"}
    with attempt_lease(active):
        result = cleanup_finished_job("job-a", **roots)
    assert not resume.exists() and not (old / "database.db").exists()
    assert (old / "preview.stderr.log").read_text() == "why it failed"
    assert (active / "model.bin").read_bytes() == b"active"  # attempt còn lease không bị đụng
    assert result.files_removed == 2 and result.bytes_removed == len(b"old scratch") + len(b"sparse")
    assert cleanup_finished_job("job-a", **roots).files_removed == 2  # lease đã nhả: model.bin + attempt.lock
    for unsafe in ("../workers", "missing-job", "job-a/attempt"):
        assert cleanup_finished_job(unsafe, **roots) == CleanupResult()


def test_resume_symlink_is_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "workers" / "job-a"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    (outside / "keep.bin").write_bytes(b"keep")
    root.mkdir(parents=True)
    (root / "resume").symlink_to(outside, target_is_directory=True)
    cleanup_finished_job("job-a", worker_root=tmp_path / "workers", artifact_root=tmp_path / "artifacts")
    assert (outside / "keep.bin").read_bytes() == b"keep"


def test_disk_pressure_reclaims_only_unused_attempts_and_never_resume(tmp_path: Path) -> None:
    old, active, resume = _job_with_history(tmp_path)
    protected_old, _, _ = _job_with_history(tmp_path, "job-reserved")
    with attempt_lease(active):
        result = reclaim_worker_scratch(
            worker_root=tmp_path / "workers", artifact_root=tmp_path / "artifacts", protected_jobs={"job-reserved"}
        )
    assert result.files_removed == 1 and not (old / "database.db").exists()
    assert (active / "model.bin").is_file() and (resume / "colmap-key" / "sparse" / "points3D.bin").is_file()
    assert (protected_old / "database.db").is_file()  # job đang có worker giữ chỗ
    assert reclaim_worker_scratch(
        worker_root=tmp_path / "missing", artifact_root=tmp_path / "artifacts", protected_jobs=set()
    ) == CleanupResult(errors=1)


@pytest.mark.parametrize("status", [runner.JobStatus.SUCCEEDED, runner.JobStatus.FAILED])
def test_finalize_drops_resume_only_when_job_succeeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: runner.JobStatus
) -> None:
    registry, job, confirmation = _confirmed(tmp_path / "runtime")
    reference = _publish(registry, job.job_id, "result.json", "RecFinalizeResult", runner.StageId.RGB_GEOMETRY)
    old, _, resume = _job_with_history(tmp_path, job.job_id)
    settings = Settings(product_worker_root=tmp_path / "workers")
    monkeypatch.setattr(runner, "get_settings", lambda: settings)
    monkeypatch.setattr(runner, "get_project_registry", lambda: registry)
    monkeypatch.setattr(runner, "_authorized_decision", lambda *args: (confirmation, "sha256:" + "a" * 64))
    failed = status == runner.JobStatus.FAILED
    monkeypatch.setattr(
        runner, "_run_tool", lambda *args: (int(failed), {"result_ref": reference.model_dump(mode="json")})
    )
    monkeypatch.setattr(
        runner,
        "load_finalize_result",
        lambda *args: SimpleNamespace(
            attempt_id=next(
                path.name
                for path in (tmp_path / "workers" / job.job_id).glob("finalize-*")
                if path.name != "finalize-" + "2" * 32
            ),
            error="failed" if failed else None,
            bundle_ref=reference,
        ),
    )
    monkeypatch.setattr(
        runner, "_extract_scene_stage", lambda *args: [_stage(reference, runner.StageId.OBJECT_EXTRACT)]
    )
    done = job.model_copy(update={"status": status})
    monkeypatch.setattr(registry, "record_finalize", lambda *args: done)
    assert runner.run_finalize_job(job.job_id) == done
    assert resume.exists() == failed and (old / "database.db").exists() == failed
    assert (old / "preview.stderr.log").is_file()


def test_metric_proposal_step_never_blocks_the_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Đề xuất tỉ lệ là bước phụ trợ: không bật thì không chạy gì; lỗi thì chỉ ghi log."""
    workspace = _workspace(tmp_path)
    registry = _registry(tmp_path / "runtime")
    attempt = runner._Attempt(
        registry, Settings(product_worker_root=tmp_path / "workers"), registry.get_job("job-fixture-001"), workspace
    )
    reference = _publish(
        registry, attempt.job.job_id, "preview.json", "ReconstructionPreview", runner.StageId.VISUAL_RECON
    )
    propose = Mock(return_value=None)
    monkeypatch.setattr(runner, "propose_metric", propose)
    for name in ("R2S_MOGE_PYTHON", "R2S_MOGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    runner._propose_metric(attempt, None)  # preview lỗi: không có ref
    runner._propose_metric(attempt, reference)  # runtime MoGe không cấu hình
    propose.assert_not_called()
    monkeypatch.setenv("R2S_MOGE_PYTHON", "/usr/bin/python3")
    monkeypatch.setenv("R2S_MOGE_MODEL", str(tmp_path / "model.pt"))
    runner._propose_metric(attempt, reference)  # preview.json của fixture không phải ReconstructionPreview: bị bắt
    propose.assert_not_called()
    preview = SimpleNamespace(source_visual_ref=reference)
    monkeypatch.setattr(runner.ReconstructionPreview, "model_validate_json", classmethod(lambda cls, data: preview))
    propose.side_effect = ValueError("MoGe lỗi")
    runner._propose_metric(attempt, reference)  # lỗi runtime: không ném ra ngoài
    assert propose.call_count == 1 and propose.call_args.args[:2] == (attempt.job.job_id, reference)
    assert propose.call_args.args[5] == workspace / "metric_proposal"


def test_recover_interrupted_jobs_on_worker_startup(tmp_path: Path) -> None:
    """Worker khởi động: job RUNNING có attempt lock đã nhả tự động chuyển FAILED (retryable=True)."""
    from src.models.contracts.manifests import JobStatus, StageId
    from src.services.orchestration.jobs.models import TransitionRequest
    from src.services.orchestration.jobs.worker_cli import recover_interrupted_jobs
    from src.services.orchestration.projects.models import JobCreateInput

    registry = _registry(tmp_path / "runtime")
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    # Chuyển QUEUED -> RUNNING ở VISUAL_RECON
    claimed = registry.transition_job(
        job.job_id,
        TransitionRequest(target_status=JobStatus.RUNNING, current_stage=StageId.VISUAL_RECON),
        expected_checksum=job.job_manifest_checksum,
    )
    assert claimed.status == JobStatus.RUNNING

    # Tạo attempt workspace mồ côi (không ai giữ flock)
    worker_root = tmp_path / "workers"
    workspace = worker_root / job.job_id / ("attempt-" + "c" * 32)
    workspace.mkdir(parents=True)
    (workspace / "attempt.lock").write_text("")

    settings = Settings(product_worker_root=worker_root)
    recovered = recover_interrupted_jobs(registry, settings)
    assert recovered == 1

    current = registry.get_job(job.job_id)
    assert current.status == JobStatus.FAILED
    assert current.current_stage == StageId.VISUAL_RECON
    history = registry.list_job_attempts(job.job_id)
    latest_event = history[-1]
    assert latest_event.error is not None
    assert latest_event.error.error_code == "INTERRUPTED_SHUTDOWN"
    assert latest_event.error.retryable is True
