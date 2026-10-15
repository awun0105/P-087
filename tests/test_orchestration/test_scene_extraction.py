"""Bước tách vật thể sau bundle (ADR 0006) khi chưa có runtime SAM2: lùi về tách hình học.

Fixture proof: bundle mẫu đổi job + collision mesh tổng hợp (sàn + một hộp); không phải
bằng chứng chất lượng SAMPro3D trên dữ liệu thật.
"""

import io
import logging
from pathlib import Path

import pytest
import trimesh

from src.config import Settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.floor_model import FloorFitEvidence
from src.models.contracts.manifests import StageId, StageStatus
from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.scene import SceneObjectState
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.scene.extraction import extract_scene
from src.services.orchestration.scene.floor_evidence import load_floor_fit_evidence
from tests.test_orchestration.test_finalize_flow import _confirmed

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "reconstruction_bundle" / "manifest.json"


def _collision(registry, job_id: str) -> ProductArtifactRef:  # noqa: ANN001
    floor = trimesh.creation.box(extents=(8, 8, 0.02))
    floor.apply_translation((0, 0, -0.01))
    pallet = trimesh.creation.box(extents=(1.0, 0.8, 0.6))
    pallet.apply_translation((1.5, 0.5, 0.3))
    buffer = io.BytesIO()
    trimesh.util.concatenate([floor, pallet.subdivide_to_size(0.05)]).export(buffer, file_type="glb")
    payload = buffer.getvalue()
    reference = ProductArtifactRef(
        artifact_type="CanonicalGeometry",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/rec05/collision.glb",
        artifact_checksum=sha256_bytes(payload),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=job_id,
    )
    return FilesystemArtifactStore(registry.runtime_resolver).publish(reference, payload)


def test_without_sam2_runtime_falls_back_to_geometric_candidates(tmp_path: Path) -> None:
    registry, job, _ = _confirmed(tmp_path)
    text = _FIXTURE.read_text(encoding="utf-8").replace("job-fixture-001", job.job_id)
    bundle = ReconstructionBundle.model_validate_json(text)
    bundle = bundle.model_copy(update={"canonical_geometry_ref": _collision(registry, job.job_id)})
    settings = Settings(product_scene_runtime_python=None, product_sam2_checkpoint=None)

    stage = extract_scene(registry, job, bundle, settings, tmp_path / "work")

    assert stage.stage_id == StageId.OBJECT_EXTRACT and stage.status == StageStatus.SUCCEEDED
    scene = registry.scene.current(job.job_id).scene
    assert scene.scene_revision == "rev-001" and stage.artifact_uri.endswith("scene_ir.rev-001.json")
    assert scene.provenance["object_extraction"] == "geometric_voxel_components_v1"
    floor_fit = scene.provenance["floor_fit"]
    floor_fit_ref = ProductArtifactRef.model_validate(floor_fit["artifact_ref"])
    floor_evidence = load_floor_fit_evidence(
        floor_fit_ref,
        registry.runtime_resolver.require,
        expected_source_artifact_ref=bundle.canonical_geometry_ref,
        expected_profile_checksum=floor_fit["profile_checksum"],
    )
    assert isinstance(floor_evidence, FloorFitEvidence)
    assert floor_evidence.point_cloud_checksum == floor_fit["point_cloud_checksum"]
    assert scene.environment.geometry_ref == bundle.canonical_geometry_ref
    (pallet,) = scene.objects
    assert pallet.state == SceneObjectState.CANDIDATE and not pallet.active
    assert pallet.source_collision is not None
    assert pallet.source_collision.source_geometry_ref == bundle.canonical_geometry_ref
    assert pallet.source_collision.extraction_revision == "rev-001"
    assert pallet.source_collision.source_transform == pallet.transform
    assert abs(pallet.transform.translation_xyz[0] - 1.5) < 0.15
    # Chạy lại (retry) không ghi đè revision đã có.
    again = extract_scene(registry, job, bundle, settings, tmp_path / "work")
    assert again.artifact_checksum == stage.artifact_checksum


@pytest.mark.parametrize("review,queue_failure", [("auto", False), ("required", False), ("auto", True)])
@pytest.mark.parametrize("method", ["shell", "objectgs"])
def test_extraction_auto_publishes_draft_then_enqueues_geometry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    review: str,
    method: str,
    queue_failure: bool,
) -> None:
    from types import SimpleNamespace

    from src.services.orchestration.scene import extraction as module
    from src.services.orchestration.scene import objectify_queue
    from src.services.orchestration.scene.objectify import ObjectifyResult

    registry, job, _ = _confirmed(tmp_path)
    bundle = ReconstructionBundle.model_validate_json(_FIXTURE.read_text().replace("job-fixture-001", job.job_id))
    bundle = bundle.model_copy(update={"canonical_geometry_ref": _collision(registry, job.job_id)})
    sealed_scene = {
        "geometry_method": method,
        "geometry_review": review,
        "refinement": "multiview_v1",
        "sam_batch": 4,
        "coacd_threshold": 0.03,
        "inpaint_max_new_gaussians": 123,
    }
    observed = []
    monkeypatch.setattr(
        module, "load_job_config", lambda *args: SimpleNamespace(scene=dict(sealed_scene)), raising=False
    )
    monkeypatch.setattr(module, "job_requires_strict_geometry", lambda *args: True)
    monkeypatch.setattr(module, "_sam2_runtime", lambda *args: SimpleNamespace(available=lambda: True))
    monkeypatch.setattr(objectify_queue, "job_bundle", lambda *args: bundle)

    def extract(*args: object, **kwargs: object) -> ObjectifyResult:
        from src.models.contracts.scene import SceneEnvironment

        observed.append(kwargs)
        if review == "auto":
            assert kwargs["scene_config"] == {
                "scene": {
                    "geometry_method": method,
                    "geometry_review": "required",
                    "refinement": "multiview_v1",
                    "sam_batch": 4,
                },
                "coacd": {"threshold": 0.03},
                "inpaint": {"max_new_gaussians": 123},
            }
        return ObjectifyResult(
            SceneEnvironment(visual_ref=bundle.visual_artifact_ref, geometry_ref=bundle.canonical_geometry_ref),
            [],
            {"object_geometry": "awaiting_review", "geometry_method": method, "geometry_review": "required"},
        )

    monkeypatch.setattr(module, "objectify_with_retry", extract)
    if queue_failure:

        def reject_request(*args: object, **kwargs: object) -> None:
            raise objectify_queue.ObjectifyRequestError("geometry queue is busy")

        monkeypatch.setattr(objectify_queue, "request", reject_request)
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'queue.db'}", product_objectify=True)
    with caplog.at_level(logging.WARNING, logger=module.__name__):
        stage = module.extract_scene(registry, job, bundle, settings, tmp_path / "work")
    assert stage.stage_id == StageId.OBJECT_EXTRACT and stage.status == StageStatus.SUCCEEDED
    scene = registry.scene.current(job.job_id).scene
    queued = objectify_queue.state(registry, settings, job.job_id)
    assert scene.provenance["object_geometry"] == "awaiting_review"
    assert stage.artifact_uri.endswith("scene_ir.rev-001.json")
    if queue_failure:
        assert scene.scene_revision == "rev-001"
        assert queued.status == "idle"
        assert any(
            record.levelno == logging.WARNING
            and job.job_id in record.getMessage()
            and "geometry queue is busy" in record.getMessage()
            for record in caplog.records
        )
    elif review == "auto":
        assert scene.provenance["geometry_review"] == "auto"
        assert queued.status == "queued" and queued.mode == "geometry" and queued.base_revision == scene.scene_revision
        # Retrying extraction after initial publication keeps the same queued operation.
        module.extract_scene(registry, job, bundle, settings, tmp_path / "retry")
        assert objectify_queue.state(registry, settings, job.job_id).operation_id == queued.operation_id
    else:
        assert queued.status == "idle"
    assert sealed_scene["geometry_review"] == review
