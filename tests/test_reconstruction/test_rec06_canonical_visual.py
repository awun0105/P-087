"""Metric visual publication: fixture orchestration và native codec proof tách biệt."""

import os
from pathlib import Path

import pytest

from src.models.contracts.identity import canonical_content_checksum
from src.services.orchestration.artifacts.errors import ArtifactChecksumError
from src.services.reconstruction.adapters.brush_runtime import BrushRuntimeSettings, VisualProcess
from src.services.reconstruction.adapters.gaussian_scale import SplatTransformSimilarityAdapter
from src.services.reconstruction.adapters.splat import SplatArtifactProcessor, SplatRuntimeSettings
from src.services.reconstruction.adapters.voxel_runtime import VoxelProcess, VoxelRuntimeSettings
from src.services.reconstruction.rgb.canonical_visual import CanonicalVisualDependencies, CanonicalVisualService
from src.services.reconstruction.rgb.canonical_visual_models import CanonicalVisualRequest
from src.services.reconstruction.rgb.visual import SplatInspection
from tests.test_reconstruction.test_rec04_brush import FixtureProcessor
from tests.test_reconstruction.test_rec05_adapter import FixtureProcess
from tests.test_reconstruction.test_rec05_scale import _rows
from tests.test_reconstruction.test_rec06_canonical_poses import pose_service


class FixturePackaging(FixtureProcessor):
    """Receipt stub chỉ kiểm plumbing; synthetic label không là native-codec proof."""

    def process_artifact(self, workspace: Path, iterations: int) -> SplatInspection:
        return super().process_artifact(workspace, iterations).model_copy(update={"revision": "afbc281"})


def visual_service(root: Path, native: bool = False) -> tuple:
    """Metric approval là fixture; native=True chỉ thay hai process adapters bằng codec thật."""
    module = os.environ.get("REC05_TEST_SPLAT_MODULE")
    if native and not module:
        pytest.skip("REC05_TEST_SPLAT_MODULE required for native visual publication proof")
    poses, confirmation, record = pose_service(root)
    request = CanonicalVisualRequest(
        execution_scope="synthetic_fixture",
        confirmation_ref=confirmation,
        canonical_pose_ref=poses.publish(confirmation),
    )
    module_path = Path(module or "unused").resolve()
    settings = VoxelRuntimeSettings(cli=Path("unused"), module_path=module_path)
    similarity = SplatTransformSimilarityAdapter(VoxelProcess(settings) if native else FixtureProcess(settings))
    process = VisualProcess(
        BrushRuntimeSettings(expected_version="0.3.0", runtime_identity="synthetic-publication-test")
    )
    processor = (SplatArtifactProcessor if native else FixturePackaging)(
        SplatRuntimeSettings(module_path=module_path / "dist/index.mjs" if module_path.is_dir() else module_path),
        process,
    )
    return (
        CanonicalVisualService(CanonicalVisualDependencies(poses.canonicalizer, similarity, processor)),
        request,
        record,
    )


def test_fixture_publication_has_real_resolvable_refs(tmp_path: Path) -> None:
    """Store/public metadata đúng shape, không nâng fixture bytes thành Brush acceptance."""
    service, request, record = visual_service(tmp_path)
    reference = service.execute(request, tmp_path / "canonical")
    manifest = service.load(reference)
    assert manifest.visual.format == "sog"
    assert manifest.visual.producer_stage == "ST-VISUAL-RECON"
    assert reference.producer_stage == "ST-METRIC-CANONICALIZE"
    assert manifest.delivery_ref().source_provenance["evidence_kind"] == "synthetic_fixture"
    assert manifest.visual.provenance["brush_compatibility_proof"] is False
    assert manifest.visual.provenance["measurement_ref"] == record.preview.request.anchor.measurement_ref.model_dump(
        mode="json"
    )
    assert str(tmp_path) not in manifest.model_dump_json()
    assert manifest.visual.provenance["source_master"] == record.preview.request.anchor.source_master.model_dump(
        mode="json"
    )
    assert service.visuals.require(manifest.delivery_ref()).read_bytes() == b"fixture SOG"
    assert service.visuals.require(manifest.master_ref).is_file()
    assert manifest.artifact_checksum == canonical_content_checksum(manifest, "artifact_checksum")
    raw = service.visuals.load(record.preview.request.source_visual)
    frames = service.visuals.poses.frames.load(raw.source_frame_set)
    assert manifest.visual.source_input_checksum == frames.input_manifest_checksum


def test_product_default_rejects_fixture_before_execution(tmp_path: Path) -> None:
    """Không có opt-in synthetic thì fixture confirmation không cho publish product."""
    service, request, _ = visual_service(tmp_path)
    product = request.model_copy(update={"execution_scope": "product"})
    with pytest.raises(ValueError, match="synthetic confirmation"):
        service.execute(product, tmp_path / "product")
    assert not (tmp_path / "product").exists()


def test_visual_requires_published_canonical_poses(tmp_path: Path) -> None:
    """Không nhận raw poses trong request dù cùng scene/master."""
    service, request, record = visual_service(tmp_path)
    bad = request.model_copy(update={"canonical_pose_ref": record.preview.source_camera_poses})
    with pytest.raises(ValueError, match="not a REC-06 canonical"):
        service.execute(bad, tmp_path / "attempt")
    assert not (tmp_path / "attempt").exists()


@pytest.mark.parametrize("target", ["master", "delivery", "manifest"])
def test_corrupted_published_bytes_rejected(tmp_path: Path, target: str) -> None:
    """Consumer kiểm tất cả derivative bytes, không chỉ checksum manifest."""
    service, request, _ = visual_service(tmp_path)
    reference = service.execute(request, tmp_path / "canonical")
    manifest = service.load(reference)
    ref = {"master": manifest.master_ref, "delivery": manifest.delivery_ref(), "manifest": reference}[target]
    service.visuals.require(ref).write_bytes(b"corrupted")
    with pytest.raises(ArtifactChecksumError, match="checksum mismatch"):
        service.load(reference)


@pytest.mark.parametrize("change", ["revision", "count", "mutate_master"])
def test_bad_packager_cannot_publish_manifest(tmp_path: Path, change: str) -> None:
    """Exit thành công không đủ nếu codec/giới hạn inventory/source integrity sai."""
    service, request, _ = visual_service(tmp_path)
    previous = list((tmp_path / "store").rglob("visual.json"))
    original = service.deps.processor.process_artifact

    def broken(workspace: Path, iterations: int) -> SplatInspection:
        result = original(workspace, iterations)
        if change == "mutate_master":
            (workspace / "output/visual.ply").write_bytes(b"mutated")
            return result
        return result.model_copy(update={"revision": "unknown"} if change == "revision" else {"num_gaussians": 255})

    service.deps.processor.process_artifact = broken
    with pytest.raises(ValueError, match="codec revision|Gaussian/SH inventory|changed the canonical"):
        service.execute(request, tmp_path / "canonical")
    assert list((tmp_path / "store").rglob("visual.json")) == previous


def test_changed_manifest_provenance_rejected(tmp_path: Path) -> None:
    """Source ref provenance không được đổi để nâng evidence kind."""
    service, request, _ = visual_service(tmp_path)
    reference = service.execute(request, tmp_path / "canonical")
    bad = reference.model_copy(update={"source_provenance": {"evidence_kind": "real_measurement"}})
    with pytest.raises(ValueError, match="identity/provenance mismatch"):
        service.load(bad)


def test_native_metric_ply_and_sog_publication(tmp_path: Path) -> None:
    """Codec thật áp s=2/Rz90/t=(10,20,30), encode+read SOG; không là browser QA."""
    service, request, record = visual_service(tmp_path, native=True)
    raw = service.visuals.require(record.preview.request.anchor.source_master)
    original = raw.read_bytes()
    reference = service.execute(request, tmp_path / "native")
    manifest = service.load(reference)
    rows = _rows(service.visuals.require(manifest.master_ref))
    assert len(rows) == manifest.inspection.num_gaussians == 256
    for before, after in zip(_rows(raw), rows, strict=True):
        assert tuple(after[key] for key in ("x", "y", "z")) == pytest.approx(
            (10 - 2 * before["y"], 20 + 2 * before["x"], 30 + 2 * before["z"]),
            abs=2e-6,
        )
    assert raw.read_bytes() == original
    assert manifest.inspection.ply_to_sog == "identity_in_ply_storage_space"
    assert manifest.transform_receipt.revision == manifest.inspection.revision == "afbc281"
    assert service.visuals.require(manifest.delivery_ref()).read_bytes().startswith(b"PK")
    assert manifest.delivery_ref().artifact_checksum != record.preview.request.anchor.source_master.artifact_checksum
