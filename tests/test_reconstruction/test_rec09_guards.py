"""Regression cho auto-confirm và sensor/world confusion ở REC-09 audit."""

import math
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.reconstruction import AlignmentStatus
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.orchestration.artifacts.errors import ArtifactChecksumError
from src.services.reconstruction.alignment import (
    AlignmentRequest,
    RgbLidarAlignmentService,
    compose_transforms,
    invert_transform,
    load_torwic_cam_to_lidar_transform,
    normalize_torwic_extrinsics,
)
from tests.test_reconstruction.rec09_fixtures import alignment_fixture


def _reference(kind: str) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=kind,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/audit-rec09/{kind}.bin",
        artifact_checksum="sha256:" + "1" * 64,
        data_class="derived",
        producer_stage="ST-RGB-GEOMETRY" if kind == "RgbGeometry" else "ST-LIDAR-INGEST",
        job_id="audit-rec09",
    )


def _request() -> AlignmentRequest:
    return AlignmentRequest(
        job_id="audit-rec09",
        rgb_geometry_ref=_reference("RgbGeometry"),
        lidar_geometry_ref=_reference("LiDARGeometryArtifact"),
        transform_target_from_source=Transform(
            parent_frame="world",
            local_frame="lidar_world",
            translation_xyz=(0, 0, 0),
            rotation_quaternion_xyzw=(0, 0, 0, 1),
        ),
    )


def test_request_does_not_default_to_confirmed_same_scene() -> None:
    request = _request()
    assert request.status == "DECLARED"
    assert request.same_scene_attestation is False


def test_no_verifier_or_payloads_cannot_publish_confirmed(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(ArtifactResolver(tmp_path))
    request = _request().model_copy(update={"status": AlignmentStatus.CONFIRMED, "same_scene_attestation": True})
    with pytest.raises(ValueError):
        RgbLidarAlignmentService(store).align(request)
    assert not list(tmp_path.rglob("alignment_evidence.json"))


def test_sensor_extrinsic_is_not_relabelled_as_world(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration.txt"
    values = dict(px=1, py=2, pz=3, qx=0, qy=0, qz=0, qw=1)
    calibration.write_text("\n".join(f"T_cam1_os.{key}: {value}" for key, value in values.items()))
    transform = load_torwic_cam_to_lidar_transform(calibration)
    assert transform.parent_frame == "os_sensor"
    assert transform.local_frame == "azure_left_camera"
    assert transform.translation_xyz == (1, 2, 3)


def test_zero_quaternion_is_actionable_validation_error() -> None:
    with pytest.raises(ValueError, match="quaternion"):
        normalize_torwic_extrinsics((0, 0, 0), (0, 0, 0, 0))


@pytest.mark.parametrize("member", ["rgb", "lidar", "review"])
def test_tampered_source_or_review_is_rejected(tmp_path: Path, member: str) -> None:
    service, request = alignment_fixture(tmp_path)
    refs = {"rgb": request.rgb_geometry_ref, "lidar": request.lidar_geometry_ref, "review": request.evidence_refs[0]}
    service.resolve(refs[member]).write_bytes(b"tampered after review")
    with pytest.raises((ValueError, ArtifactChecksumError)):
        service.align(request)


def test_review_binds_exact_transform_and_evidence(tmp_path: Path) -> None:
    service, request = alignment_fixture(tmp_path)
    changed = request.transform_target_from_source.model_copy(update={"translation_xyz": (7, 8, 9)})
    with pytest.raises(ValueError, match="not authorized"):
        service.align(request.model_copy(update={"transform_target_from_source": changed}))
    record, ref = service.align(request)
    assert service.load(ref) == record
    assert record.evidence_refs == request.evidence_refs
    with pytest.raises(ValueError, match="provenance mismatch"):
        service.load(ref.model_copy(update={"source_provenance": {}}))


def test_loaded_record_revalidates_source_bytes(tmp_path: Path) -> None:
    service, request = alignment_fixture(tmp_path)
    _, ref = service.align(request)
    service.resolve(request.lidar_geometry_ref).write_bytes(b"changed source")
    with pytest.raises((ValueError, ArtifactChecksumError)):
        service.load(ref)


def test_nontrivial_frame_composition_and_inverse() -> None:
    parent = Transform(
        parent_frame="world",
        local_frame="camera",
        translation_xyz=(1, 2, 3),
        rotation_quaternion_xyzw=(0, 0, math.sqrt(0.5), math.sqrt(0.5)),
    )
    local = Transform(
        parent_frame="camera", local_frame="lidar", translation_xyz=(4, 5, 6), rotation_quaternion_xyzw=(0, 0, 0, 1)
    )
    result = compose_transforms(parent, local)
    assert result.translation_xyz == pytest.approx((-4, 6, 9))
    assert (result.parent_frame, result.local_frame) == ("world", "lidar")
    assert invert_transform(invert_transform(result)).translation_xyz == pytest.approx(result.translation_xyz)
    with pytest.raises(ValueError, match="disconnected frames"):
        compose_transforms(local, parent)


@pytest.mark.parametrize("failure", ["duplicate", "nan", "missing"])
def test_invalid_calibration_values_fail_closed(tmp_path: Path, failure: str) -> None:
    calibration = tmp_path / "calibration.txt"
    values = dict(px=1, py=2, pz=3, qx=0, qy=0, qz=0, qw=1)
    if failure == "nan":
        values["px"] = float("nan")
    elif failure == "missing":
        del values["qx"]
    text = "\n".join(f"T_cam1_os.{key}={value}" for key, value in values.items())
    calibration.write_text(text + ("\nT_cam1_os.px: 1" if failure == "duplicate" else ""))
    with pytest.raises(ValueError):
        load_torwic_cam_to_lidar_transform(calibration)
