"""REC-11 fixture publication và lỗi CLI; không claim full reconstruction acceptance."""

import json
from pathlib import Path

import pytest

from src.models.contracts.manifests import JobStatus, StageStatus
from src.services.reconstruction.bundle import BundleBuildRequest
from src.services.reconstruction.bundle_validation import BundleDependencies
from src.services.reconstruction.worker import (
    ReconstructionWorker,
    WorkerConfig,
    WorkerExecutionResult,
    main,
)
from tests.test_reconstruction.support.rec10_fixtures import simple_bundle_fixture


def _config(root: Path, request: BundleBuildRequest) -> WorkerConfig:
    return WorkerConfig(
        job_id=request.job_id,
        store_root=root / "store",
        workspace_dir=root / "work",
        bundle_request=request,
    )


def _args(root: Path, request_file: Path) -> list[str]:
    return [
        "--job-id",
        "audit",
        "--store-root",
        str(root / "store"),
        "--workspace",
        str(root / "work"),
        "--request",
        str(request_file),
        "--output",
        str(root / "result.json"),
    ]


def test_worker_run_success_is_verified_fixture_publication(tmp_path: Path) -> None:
    writer, deps, request = simple_bundle_fixture(tmp_path)
    result = ReconstructionWorker(_config(tmp_path, request), writer, deps).run()
    assert result.status == JobStatus.SUCCEEDED
    assert result.error is None and result.bundle_ref is not None
    assert result.stage_artifacts[0].status == StageStatus.SUCCEEDED
    payload = json.loads(writer.resolver.require(result.bundle_ref).read_text())
    assert payload["provenance"]["evidence_kind"] == "synthetic_fixture"


def test_worker_rejects_unresolved_bytes(tmp_path: Path) -> None:
    writer, deps, request = simple_bundle_fixture(tmp_path)
    writer.resolver.require(request.visual_artifact_ref).unlink()
    result = ReconstructionWorker(_config(tmp_path, request), writer, deps).run()
    assert result.status == JobStatus.FAILED
    assert result.bundle_ref is None and result.error is not None
    assert result.stage_artifacts[0].status == StageStatus.FAILED
    assert not list((tmp_path / "store").rglob("bundle.json"))


def test_worker_failure_is_redacted(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    writer, _, request = simple_bundle_fixture(tmp_path)

    def fail(reference: object) -> Path:
        raise RuntimeError("private: " + str(tmp_path) + "/sensitive/cloud.ply")

    result = ReconstructionWorker(_config(tmp_path, request), writer, BundleDependencies(fail)).run()
    assert result.status == JobStatus.FAILED
    assert str(tmp_path) not in result.model_dump_json() + caplog.text
    assert result.error.details["exception_type"] == "RuntimeError"


def test_worker_config_rejects_cross_job(tmp_path: Path) -> None:
    _, _, request = simple_bundle_fixture(tmp_path)
    with pytest.raises(ValueError, match="job_id must match"):
        WorkerConfig(job_id="other", store_root=tmp_path, workspace_dir=tmp_path, bundle_request=request)


def test_worker_cli_missing_request_is_usage_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--job-id", "audit", "--store-root", str(tmp_path), "--workspace", str(tmp_path)])
    assert error.value.code == 2


def test_worker_cli_does_not_authorize_fixture_by_itself(tmp_path: Path) -> None:
    _, _, request = simple_bundle_fixture(tmp_path)
    request_file = tmp_path / "request.json"
    request_file.write_text(request.model_dump_json())
    assert main(_args(tmp_path, request_file)) == 1
    output = tmp_path / "result.json"
    result = WorkerExecutionResult.model_validate_json(output.read_text())
    assert result.status == JobStatus.FAILED
    assert result.bundle_ref is None
    original = output.read_bytes()
    assert main(_args(tmp_path, request_file)) == 2
    assert output.read_bytes() == original


@pytest.mark.parametrize("field", ["job_id", "store_root", "workspace_dir"])
def test_worker_cli_config_binding(tmp_path: Path, field: str) -> None:
    _, _, request = simple_bundle_fixture(tmp_path)
    config = _config(tmp_path, request).model_dump(mode="json")
    config[field] = "other" if field == "job_id" else str(tmp_path / "other")
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(config))
    assert main(_args(tmp_path, request_file)) == 2
    assert not (tmp_path / "result.json").exists()


@pytest.mark.parametrize("content", ["not JSON", "[]", '{"bundle_request": {}}'])
def test_worker_cli_malformed_request_fails(tmp_path: Path, content: str) -> None:
    request_file = tmp_path / "request.json"
    request_file.write_text(content)
    assert main(_args(tmp_path, request_file)) == 2
