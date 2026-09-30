"""Bước tách vật thể sau bundle (ADR 0006) khi chưa có runtime SAM2: lùi về tách hình học.

Fixture proof: bundle mẫu đổi job + collision mesh tổng hợp (sàn + một hộp); không phải
bằng chứng chất lượng SAMPro3D trên dữ liệu thật.
"""

import io
from pathlib import Path

import trimesh

from src.config import Settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId, StageStatus
from src.models.contracts.reconstruction import ReconstructionBundle
from src.models.contracts.scene import SceneObjectState
from src.services.orchestration.artifacts import FilesystemArtifactStore, sha256_bytes
from src.services.orchestration.scene_extraction import extract_scene
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
    assert scene.environment.geometry_ref == bundle.canonical_geometry_ref
    (pallet,) = scene.objects
    assert pallet.state == SceneObjectState.CANDIDATE and not pallet.active
    assert abs(pallet.transform.translation_xyz[0] - 1.5) < 0.15
    # Chạy lại (retry) không ghi đè revision đã có.
    again = extract_scene(registry, job, bundle, settings, tmp_path / "work")
    assert again.artifact_checksum == stage.artifact_checksum
