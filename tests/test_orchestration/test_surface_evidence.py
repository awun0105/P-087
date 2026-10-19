"""Surface reports must bind immutable object/source/result identities before publication."""

import hashlib
import json

import pytest

from src.services.orchestration.scene.surface_evidence import publish_surface_artifacts


def item_fixture(tmp_path):
    payload = b"rejected surface fixture, not a mesh quality claim"
    path = tmp_path / "mesh.glb"
    path.write_bytes(payload)
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    item = dict(path=str(path), raw_path=str(path), checksum=digest, raw_checksum=digest, quality_passed=False)
    for kind in ("quality_report", "repair_report"):
        report = dict(object_id="candidate-001", source_checksum=digest, result_checksum=digest, passed=False)
        report_path = tmp_path / (kind + ".json")
        report_path.write_text(json.dumps(report))
        item[kind + "_path"] = str(report_path)
        item[kind + "_checksum"] = "sha256:" + hashlib.sha256(report_path.read_bytes()).hexdigest()
    return item


def test_rejected_surface_publishes_typed_reports_but_never_an_accepted_mesh(tmp_path):
    item = item_fixture(tmp_path)
    saved = {}

    def publish(reference, payload):
        saved[reference.artifact_uri] = payload
        return reference

    refs = publish_surface_artifacts("job-test", "candidate-001", item, publish)
    assert refs["surface"]["artifact_type"] == "ObjectSurfaceCandidateMesh"
    assert refs["quality_report"]["artifact_type"] == "ObjectSurfaceQualityReport"
    assert len(saved) == 4
    assert all(ref["job_id"] == "job-test" for ref in refs.values())


@pytest.mark.parametrize("failure", ["object_id", "source_checksum", "result_checksum", "passed"])
def test_inconsistent_quality_evidence_cannot_be_published(tmp_path, failure):
    item = item_fixture(tmp_path)
    path = tmp_path / "quality_report.json"
    report = json.loads(path.read_text())
    report[failure] = True if failure == "passed" else "incorrect-binding"
    path.write_text(json.dumps(report))
    item["quality_report_checksum"] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def forbidden(*args):
        pytest.fail("unbound quality reports must be rejected before any publication")

    with pytest.raises(ValueError, match="bind"):
        publish_surface_artifacts("job-test", "candidate-001", item, forbidden)
