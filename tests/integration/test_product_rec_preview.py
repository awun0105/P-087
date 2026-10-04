"""Published REC checkpoint→PRODUCT→artifact bytes, fixture tools không phải GPU."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.models.contracts.manifests import JobManifest, StageArtifact
from src.services.orchestration.artifacts import ArtifactChecksumError, with_canonical_checksum
from src.services.orchestration.projects.preview import load_job_preview
from src.services.reconstruction import verify_prepared_preview
from tests.test_reconstruction.test_rec11_preview import preview


def test_published_preview_can_be_consumed_without_scene_ir(tmp_path: Path) -> None:
    worker, request, resolver = preview(tmp_path)
    _, result_ref = worker.run(request, tmp_path / "run")
    receipt = verify_prepared_preview(result_ref, resolver.require)
    assert receipt.preview_ref is not None
    ref = receipt.preview_ref
    fixture = Path(__file__).resolve().parents[2] / "fixtures/mock_job/job_manifest.json"
    job = JobManifest.model_validate_json(fixture.read_bytes())
    job = with_canonical_checksum(
        job.model_copy(
            update={
                "job_id": request.job_id,
                "input_manifest_checksum": request.source_input_checksum,
                "stage_artifacts": [
                    StageArtifact(
                        stage_id="ST-VISUAL-RECON",
                        status="SUCCEEDED",
                        artifact_type=ref.artifact_type,
                        artifact_uri=ref.artifact_uri,
                        artifact_checksum=ref.artifact_checksum,
                        data_class=ref.data_class,
                        completed_at=datetime.now(UTC),
                    )
                ],
            }
        ),
        "job_manifest_checksum",
    )
    published = load_job_preview(job, resolver)
    assert published.metric_status == "UNCONFIRMED" and published.unit == "arbitrary"
    assert resolver.require(published.delivery_ref).read_bytes() == b"fixture SOG"
    with pytest.raises(ArtifactChecksumError):
        load_job_preview(job.model_copy(update={"input_manifest_checksum": "sha256:" + "f" * 64}), resolver)
    resolver.require(published.delivery_ref).write_bytes(b"tampered")
    with pytest.raises(ArtifactChecksumError):
        load_job_preview(job, resolver)
