"""Failure evidence survives scratch cleanup and never publishes a replacement scene."""

import hashlib
import json
import shutil
from types import SimpleNamespace

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.orchestration.scene.diagnostics import capture_attempt
from src.services.process_control import ProcessCancelledError
from src.services.scene.diagnostic_report import export_masks, load_evidence, render_report, trace_object
from src.services.scene.diagnostics import EvidenceRecorder


@pytest.mark.parametrize("error_type,status", [(ValueError, "failed"), (ProcessCancelledError, "cancelled")])
def test_failed_or_cancelled_attempt_is_replayable_after_workspace_removal(tmp_path, error_type, status):
    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    workspace = tmp_path / "attempt"
    trace = EvidenceRecorder(workspace / "evidence", "membership")
    trace.emit("object_binding", object_id="candidate-001", seed=3, gaussian_count=90, retained=True)
    trace.emit("object_binding", object_id="candidate-002", seed=4, gaussian_count=100, retained=True)
    error = error_type("controlled failure /private/input.ply")

    def fail():
        raise error

    with pytest.raises(error_type) as caught:
        capture_attempt(
            fail,
            job=SimpleNamespace(job_id="job-test"),
            bundle=SimpleNamespace(),
            workspace=workspace,
            publish=store.publish,
            input_revision="rev-017",
        )
    assert caught.value is error
    reference = ProductArtifactRef.model_validate_json((workspace / "evidence-ref.json").read_bytes())
    shutil.rmtree(workspace)
    payload = resolver.require(reference).read_bytes()
    manifest = load_evidence(payload, checksum=reference.artifact_checksum, job_id="job-test")
    assert manifest.status == status and manifest.input_revision == "rev-017"
    assert "/private/" not in payload.decode()
    selected = trace_object(manifest, "candidate-001")
    assert not any(event.get("object_id") == "candidate-002" for event in selected)
    assert "candidate-001" in render_report(manifest, "candidate-001")
    with pytest.raises(ValueError, match="checksum"):
        load_evidence(payload + b" ", checksum=reference.artifact_checksum)
    with pytest.raises(ValueError, match="job"):
        load_evidence(payload, checksum=reference.artifact_checksum, job_id="another-job")


def test_evidence_store_failure_cannot_replace_primary_failure_or_success(tmp_path, caplog):
    def unavailable(*args):
        raise OSError("disk full")

    failure = RuntimeError("producer failed")

    def fail():
        raise failure

    args = dict(
        job=SimpleNamespace(job_id="job-test"),
        bundle=SimpleNamespace(),
        workspace=tmp_path,
        publish=unavailable,
        input_revision="rev-001",
    )
    with pytest.raises(RuntimeError) as caught:
        capture_attempt(fail, **args)
    assert caught.value is failure
    result = SimpleNamespace(provenance={}, labels=b"unchanged", collider=b"unchanged")
    assert capture_attempt(lambda: result, **args) is result
    assert result.labels == result.collider == b"unchanged"
    assert result.provenance["object_pipeline_evidence_status"] == "unavailable"
    assert "evidence unavailable" in caplog.text


def test_success_evidence_is_bounded_and_binding_does_not_change_result(tmp_path):
    saved = {}

    def publish(reference, payload):
        saved[reference.artifact_checksum] = payload
        return reference

    trace = EvidenceRecorder(tmp_path / "evidence", "sam", event_budget=180, mask_budget=1)
    for index in range(30):
        trace.emit("decision", record=index)
    trace.mask("sample", b"mask", (1, 32))
    result = SimpleNamespace(provenance={}, labels=b"source")
    output = capture_attempt(
        lambda: result,
        job=SimpleNamespace(job_id="job-test"),
        bundle=SimpleNamespace(),
        workspace=tmp_path,
        publish=publish,
        input_revision="rev-002",
    )
    reference = output.provenance["object_pipeline_evidence"]
    payload = saved[reference["artifact_checksum"]]
    manifest = load_evidence(payload, checksum="sha256:" + hashlib.sha256(payload).hexdigest())
    assert output is result and output.labels == b"source"
    assert manifest.truncated and manifest.status == "produced"
    assert len(payload) < 16 * 1024**2
    assert json.loads(payload)["coverage"][0]["events_dropped"] > 0


def test_retained_masks_restore_exactly_and_logs_are_bounded_and_redacted(tmp_path):
    import numpy as np
    from PIL import Image

    trace = EvidenceRecorder(tmp_path / "evidence", "sam")
    mask = np.array([[1, 0, 1], [0, 1, 0]], dtype=np.uint8)
    trace.mask("view:0/prompt:9", np.packbits(mask).tobytes(), mask.shape)
    (tmp_path / "lift.log").write_text(
        "old output\n" * 10000 + "OOM -I/private/build API_KEY=topsecret Authorization: Bearer credential\n"
    )
    saved = {}

    def publish(reference, payload):
        saved[reference.artifact_checksum] = payload
        return reference

    result = capture_attempt(
        lambda: SimpleNamespace(provenance={}),
        job=SimpleNamespace(job_id="job-test"),
        bundle=SimpleNamespace(),
        workspace=tmp_path,
        publish=publish,
        input_revision="rev-001",
    )
    checksum = result.provenance["object_pipeline_evidence"]["artifact_checksum"]
    manifest = load_evidence(saved[checksum], checksum=checksum)
    log = manifest.log_tails["lift.log"]
    assert len(log) < 8300 and "OOM" in log
    assert all(secret not in log for secret in ["/private", "topsecret", "credential"])
    assert next(event for event in manifest.events if event["kind"] == "mask_sample")["key"] == "view:0/prompt:9"
    assert export_masks(manifest, tmp_path / "png") == 1
    image = np.asarray(Image.open(next((tmp_path / "png").glob("*.png"))))
    np.testing.assert_array_equal(image > 0, mask > 0)


def test_object_report_links_prompt_instance_seed_and_exports_without_other_objects(tmp_path):
    from src.models.contracts.object_diagnostics import ObjectPipelineEvidence

    manifest = ObjectPipelineEvidence(
        job_id="job-test",
        run_id="run-test",
        input_revision="rev-001",
        status="produced",
        bundle_checksum="sha256:" + "0" * 64,
        events=[
            dict(stage="sam2", kind="mask_decision", prompt=17, accepted=False),
            dict(stage="segmentation", kind="instance_decision", instance_key="key", prompts=[17]),
            dict(stage="seeds", kind="seed_decision", instance_key="key", seed=3),
            dict(stage="membership", kind="object_binding", seed=3, object_id="candidate-001"),
            dict(stage="objectgs", kind="configured", label_to_object_id={"1": "candidate-001", "2": "candidate-002"}),
            dict(stage="objectgs", kind="stage_completed", phase="export-1"),
            dict(stage="objectgs", kind="stage_failed", phase="export-2"),
        ],
    )
    report = render_report(manifest, "candidate-001")
    assert '"prompt": 17' in report and '"seed": 3' in report
    assert "export-1" in report and "export-2" not in report
    assert "Quyết định loại/cảnh báo đầu tiên" in report


def test_cli_reads_published_evidence_after_scratch_cleanup(tmp_path, monkeypatch):
    from scripts.scene import diagnose_object
    from src.services.orchestration import projects

    resolver = ArtifactResolver(tmp_path / "artifacts")
    store = FilesystemArtifactStore(resolver)
    workspace = tmp_path / "attempt"
    result = capture_attempt(
        lambda: SimpleNamespace(provenance={}),
        job=SimpleNamespace(job_id="job-test"),
        bundle=SimpleNamespace(),
        workspace=workspace,
        publish=store.publish,
        input_revision="rev-009",
    )
    checksum = result.provenance["object_pipeline_evidence"]["artifact_checksum"]
    shutil.rmtree(workspace)
    registry = SimpleNamespace(runtime_resolver=resolver, get_job=lambda job_id: None)
    monkeypatch.setattr(projects, "get_project_registry", lambda: registry)
    output = tmp_path / "report.md"
    monkeypatch.setattr(
        "sys.argv", ["diagnose_object", "--job-id", "job-test", "--checksum", checksum, "--output", str(output)]
    )
    assert diagnose_object.main() == 0
    assert "rev-009" in output.read_text()


def test_corrupt_mask_sample_cannot_be_exported(tmp_path):
    from src.models.contracts.object_diagnostics import ObjectPipelineEvidence

    manifest = ObjectPipelineEvidence(
        job_id="job-test",
        run_id="run-test",
        input_revision="rev-001",
        status="produced",
        bundle_checksum="sha256:" + "0" * 64,
        samples={"sample.bits.zlib": "eA=="},
        events=[
            dict(
                stage="sam",
                kind="mask_sample",
                file="sample.bits.zlib",
                shape=[2, 3],
                packed_checksum="sha256:" + "0" * 64,
            )
        ],
    )
    with pytest.raises(ValueError, match="packed mask size"):
        export_masks(manifest, tmp_path / "masks")
