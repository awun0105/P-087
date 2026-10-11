"""Checksum-bound target geometry adapter tests; no worker/GPU dependencies."""

import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.floor_model import FloorFitProfile, FloorModel, FloorPrior
from src.models.contracts.input_assembly import InputRole
from src.models.contracts.manifests import StageId
from src.models.contracts.rgb_lidar_registration import (
    DistanceUnit,
    RegistrationInputMode,
    RegistrationProfile,
    RegistrationROI,
    RegistrationSourceBinding,
    seal_registration_profile,
    seal_registration_request,
)
from src.services.orchestration.artifacts.errors import ArtifactChecksumError
from src.services.orchestration.artifacts.store import ArtifactResolver
from src.services.orchestration.jobs.registration_targets import (
    RegistrationTargetResolutionError,
    RegistrationTargetResolver,
)
from src.services.orchestration.scene.floor_evidence import publish_floor_fit_evidence
from src.services.reconstruction.alignment.bev_search import RegistrationFloorPlane

_JOB = "job-registration-target"
_PROJECT = "project-registration-target"
_ZERO = "sha256:" + "0" * 64


def _checksum(value: bytes | str) -> str:
    payload = value.encode() if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _collision_glb(triangle_repeats: int = 1) -> bytes:
    """Encode an asymmetric tetrahedron with the pinned collision GLB layout."""
    positions = ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 4.0))
    tetrahedron = (0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3)
    indices = tetrahedron * triangle_repeats
    binary = b"".join(struct.pack("<fff", *point) for point in positions)
    binary += struct.pack(f"<{len(indices)}I", *indices)
    position_bytes = len(positions) * 12
    document = {
        "asset": {"version": "2.0", "generator": "splat-transform"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": position_bytes, "target": 34962},
            {
                "buffer": 0,
                "byteOffset": position_bytes,
                "byteLength": len(binary) - position_bytes,
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": [0.0, 0.0, 0.0],
                "max": [2.0, 3.0, 4.0],
            },
            {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
        ],
    }
    encoded = json.dumps(document, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    return (
        struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
        + struct.pack("<I4s", len(encoded), b"JSON")
        + encoded
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )


def _floor_model(status: str = "supported") -> FloorModel:
    profile = FloorFitProfile()
    common = {
        "schema_version": "1.0",
        "source_checksum": _checksum("floor-source-points"),
        "profile_checksum": profile.checksum(),
        "profile": profile,
        "point_count": 100,
        "fit_point_count": 100,
        "inlier_count": 95,
        "inlier_ratio": 0.95,
        "coverage_area_m2": 4.0,
    }
    if status == "supported":
        return FloorModel(
            status="supported",
            prior=FloorPrior(up_direction_world=(0.0, 0.0, 1.0), point_on_floor_world=(0.0, 0.0, 0.0)),
            median_abs_residual_m=0.002,
            robust_noise_sigma_m=0.005,
            floor_band_m=0.02,
            plane_normal_world=(0.0, 0.0, 1.0),
            plane_offset_m=0.0,
            **common,
        )
    if status == "confirmed_prior_fallback":
        fallback = common | {"schema_version": "1.1"}
        return FloorModel(
            status="confirmed_prior_fallback",
            fallback_reason="insufficient_points",
            prior=FloorPrior(up_direction_world=(0.0, 0.0, 1.0), point_on_floor_world=(0.0, 0.0, 0.0)),
            floor_band_m=0.02,
            plane_normal_world=(0.0, 0.0, 1.0),
            plane_offset_m=0.0,
            **fallback,
        )
    uncertain = common | {"fit_point_count": 0, "inlier_count": 0, "inlier_ratio": 0.0, "coverage_area_m2": 0.0}
    return FloorModel(
        status="uncertain",
        fallback_reason="insufficient_points",
        prior=None,
        **uncertain,
    )


def _publish(
    root: Path,
    name: str,
    payload: bytes,
    artifact_type: str,
    stage: StageId,
    *,
    source_provenance: dict | None = None,
) -> ProductArtifactRef:
    uri = f"artifact://jobs/{_JOB}/registration/{name}"
    path = root / "jobs" / _JOB / "registration" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=uri,
        artifact_checksum=_checksum(payload),
        data_class="derived",
        producer_stage=stage,
        job_id=_JOB,
        source_provenance=source_provenance,
    )


def _profile(*, max_points_per_map: int = 250_000, max_source_points: int = 20_000_000) -> RegistrationProfile:
    return seal_registration_profile(
        {
            "profile_id": "registration-target-test",
            "max_points_per_map": max_points_per_map,
            "max_source_points": max_source_points,
            "profile_checksum": _ZERO,
        }
    )


def _request(
    geometry_ref: ProductArtifactRef,
    floor_refs: list[ProductArtifactRef],
    *,
    profile: RegistrationProfile | None = None,
    floor_state: str = "supported",
    source_mode: RegistrationInputMode = RegistrationInputMode.STATIC_CLOUD,
    metric_state: str = "confirmed",
    metric_confirmation_ref: ProductArtifactRef | None = None,
):
    selected_profile = profile or _profile()
    source_role = (
        InputRole.REGISTERED_LIDAR_MAP
        if source_mode == RegistrationInputMode.REGISTERED_MAP
        else InputRole.STATIC_LIDAR_CLOUD
    )
    source = RegistrationSourceBinding(
        mode=source_mode,
        target_job_id=_JOB,
        authorized_project_id=_PROJECT,
        source_input_checksum=_checksum("map-source"),
        source_frame="lidar-map-frame",
        source_distance_unit=DistanceUnit.METER,
        source_point_count=min(12, selected_profile.max_source_points),
        source_format="point_cloud_pcd",
        source_header_checksum=_checksum("pcd-header"),
        source_role=source_role,
        input_assembly_id="assembly-registration-target",
        input_assembly_revision=1,
        input_assembly_checksum=_checksum("assembly-1"),
        source_file_ids=["map-file-1"],
        same_scene_attestation=True,
    )
    metric_ref = metric_confirmation_ref or ProductArtifactRef.model_validate(
        geometry_ref.source_provenance["metric_confirmation_ref"]
    )
    return seal_registration_request(
        {
            "request_id": "registration-target-request",
            "requested_by": "reviewer",
            "target_project_id": _PROJECT,
            "target_job_id": _JOB,
            "target_rgb_geometry_ref": geometry_ref,
            "expected_scene_revision": "scene-rev-1",
            "source": source,
            "metric_state": metric_state,
            "metric_confirmation_ref": metric_ref if metric_state == "confirmed" else None,
            "floor_state": floor_state,
            "floor_model_refs": floor_refs,
            "target_roi_world": RegistrationROI(min_xyz_m=(-20, -20, -2), max_xyz_m=(20, 20, 8)),
            "profile": selected_profile,
            "profile_checksum": selected_profile.profile_checksum,
            "request_checksum": _ZERO,
        }
    )


def _fixture(
    tmp_path: Path,
    *,
    triangle_repeats: int = 1,
    floor_status: str = "supported",
    floor_source: str = "master",
):
    artifact_resolver = ArtifactResolver(tmp_path)
    metric_ref = _publish(
        tmp_path,
        "metric.json",
        b"metric-confirmation",
        "RGBMetricConfirmation",
        StageId.METRIC_CANONICALIZE,
    )
    master_ref = ProductArtifactRef(
        artifact_type="GaussianPLY",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{_JOB}/rec04/master.ply",
        artifact_checksum=_checksum("gaussian-master"),
        data_class="derived",
        producer_stage=StageId.VISUAL_RECON,
        job_id=_JOB,
    )
    geometry_ref = _publish(
        tmp_path,
        "collision.glb",
        _collision_glb(triangle_repeats),
        "RgbGeometry",
        StageId.RGB_GEOMETRY,
        source_provenance={
            "metric_confirmation_ref": metric_ref.model_dump(mode="json"),
            "preprocessing_provenance": {"details": {"master": master_ref.model_dump(mode="json")}},
        },
    )

    def publish(reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        path = artifact_resolver.resolve(reference.artifact_uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return reference

    floor_source_refs = {
        "geometry": geometry_ref,
        "metric": metric_ref,
        "master": master_ref,
    }
    floor_ref, _ = publish_floor_fit_evidence(
        _JOB,
        floor_source_refs[floor_source],
        _floor_model(floor_status),
        publish,
    )
    return artifact_resolver, geometry_ref, floor_ref


@pytest.mark.parametrize("source_mode", [RegistrationInputMode.REGISTERED_MAP, RegistrationInputMode.STATIC_CLOUD])
@pytest.mark.parametrize("floor_source", ["geometry", "metric", "master"])
def test_resolves_canonical_surface_samples_normals_and_measured_floor(
    tmp_path: Path, source_mode: RegistrationInputMode, floor_source: str
) -> None:
    artifact_resolver, geometry_ref, floor_ref = _fixture(tmp_path, floor_source=floor_source)
    request = _request(geometry_ref, [floor_ref], source_mode=source_mode)

    result = RegistrationTargetResolver(artifact_resolver, max_collision_glb_bytes=1_000_000).resolve(request)

    assert result.collision_surface_points_world_m.shape == (4, 3)
    np.testing.assert_allclose(
        result.collision_surface_points_world_m,
        ((2 / 3, 1, 0), (2 / 3, 0, 4 / 3), (0, 1, 4 / 3), (2 / 3, 1, 4 / 3)),
    )
    assert result.collision_surface_normals_world.shape == (4, 3)
    assert np.linalg.norm(result.collision_surface_normals_world, axis=1) == pytest.approx(np.ones(4))
    assert not result.collision_surface_points_world_m.flags.writeable
    assert result.target_floor == RegistrationFloorPlane(
        frame="world",
        normal_xyz=(0.0, 0.0, 1.0),
        offset_m=0.0,
        up_direction_xyz=(0.0, 0.0, 1.0),
        evidence_checksum=floor_ref.artifact_checksum,
    )
    assert result.mesh_vertex_count == 4
    assert result.mesh_triangle_count == 4
    assert result.target_rgb_geometry_ref == geometry_ref
    assert result.floor_evidence_ref == floor_ref
    expected_floor_source = {
        "geometry": geometry_ref,
        "metric": ProductArtifactRef.model_validate(geometry_ref.source_provenance["metric_confirmation_ref"]),
        "master": ProductArtifactRef.model_validate(
            geometry_ref.source_provenance["preprocessing_provenance"]["details"]["master"]
        ),
    }[floor_source]
    assert result.floor_fit_evidence.source_artifact_ref == expected_floor_source
    assert result.metric_confirmation_ref == ProductArtifactRef.model_validate(
        geometry_ref.source_provenance["metric_confirmation_ref"]
    )


def test_bounded_unknown_scale_keeps_target_metric_evidence_bound(tmp_path: Path) -> None:
    artifact_resolver, geometry_ref, floor_ref = _fixture(tmp_path)
    profile = seal_registration_profile(
        {
            "profile_id": "registration-target-unknown-scale",
            "scale_policy": "bounded_rgb_scale_search",
            "rgb_scale_factor_bounds": (0.9, 1.1),
            "profile_checksum": _ZERO,
        }
    )
    request = _request(geometry_ref, [floor_ref], profile=profile, metric_state="unknown")

    result = RegistrationTargetResolver(artifact_resolver, max_collision_glb_bytes=1_000_000).resolve(request)

    assert request.metric_confirmation_ref is None
    assert (
        result.metric_confirmation_ref.artifact_checksum
        == geometry_ref.source_provenance["metric_confirmation_ref"]["artifact_checksum"]
    )


def test_rejects_request_metric_confirmation_that_differs_from_geometry_provenance(tmp_path: Path) -> None:
    artifact_resolver, geometry_ref, floor_ref = _fixture(tmp_path)
    wrong_metric_ref = ProductArtifactRef.model_validate(
        geometry_ref.source_provenance["metric_confirmation_ref"]
    ).model_copy(update={"artifact_checksum": _checksum("different-metric")})
    request = _request(geometry_ref, [floor_ref], metric_confirmation_ref=wrong_metric_ref)

    with pytest.raises(RegistrationTargetResolutionError, match="differs from the RGB geometry producer"):
        RegistrationTargetResolver(artifact_resolver, max_collision_glb_bytes=1_000_000).resolve(request)


def test_surface_sampling_is_seeded_and_capped_by_the_profile(tmp_path: Path) -> None:
    artifact_resolver, geometry_ref, floor_ref = _fixture(tmp_path, triangle_repeats=300)
    request = _request(geometry_ref, [floor_ref], profile=_profile(max_points_per_map=1_000))
    target_resolver = RegistrationTargetResolver(artifact_resolver, max_collision_glb_bytes=1_000_000)

    first = target_resolver.resolve(request)
    second = target_resolver.resolve(request)

    assert first.mesh_triangle_count == 1_200
    assert first.collision_surface_points_world_m.shape == (1_000, 3)
    assert first.surface_sampling_method == "seeded_uniform_triangle_centroid_v1"
    assert np.array_equal(first.collision_surface_points_world_m, second.collision_surface_points_world_m)
    assert np.array_equal(first.collision_surface_normals_world, second.collision_surface_normals_world)


@pytest.mark.parametrize("floor_status", ["uncertain", "confirmed_prior_fallback"])
def test_refuses_unmeasured_target_floor_models(tmp_path: Path, floor_status: str) -> None:
    artifact_resolver, geometry_ref, floor_ref = _fixture(tmp_path, floor_status=floor_status)
    request = _request(geometry_ref, [floor_ref])

    with pytest.raises(RegistrationTargetResolutionError, match="measured supported plane"):
        RegistrationTargetResolver(artifact_resolver, max_collision_glb_bytes=1_000_000).resolve(request)


def test_requires_one_unambiguous_floor_reference(tmp_path: Path) -> None:
    artifact_resolver, geometry_ref, floor_ref = _fixture(tmp_path)
    request = _request(geometry_ref, [floor_ref, floor_ref])

    with pytest.raises(RegistrationTargetResolutionError, match="exactly one supported target floor evidence"):
        RegistrationTargetResolver(artifact_resolver, max_collision_glb_bytes=1_000_000).resolve(request)


def test_refuses_mesh_over_worker_byte_limit_before_decoding(tmp_path: Path) -> None:
    artifact_resolver, geometry_ref, floor_ref = _fixture(tmp_path)
    request = _request(geometry_ref, [floor_ref])

    with pytest.raises(RegistrationTargetResolutionError, match="exceeds the worker byte limit"):
        RegistrationTargetResolver(artifact_resolver, max_collision_glb_bytes=16).resolve(request)


def test_refuses_geometry_over_profile_point_budget(tmp_path: Path) -> None:
    artifact_resolver, geometry_ref, floor_ref = _fixture(tmp_path)
    request = _request(geometry_ref, [floor_ref], profile=_profile(max_source_points=3))

    with pytest.raises(RegistrationTargetResolutionError, match="exceeds the sealed point budget"):
        RegistrationTargetResolver(artifact_resolver, max_collision_glb_bytes=1_000_000).resolve(request)


def test_rechecks_exact_floor_bytes(tmp_path: Path) -> None:
    artifact_resolver, geometry_ref, floor_ref = _fixture(tmp_path)
    changed_floor_ref = floor_ref.model_copy(update={"artifact_checksum": _checksum("different-floor")})
    request = _request(geometry_ref, [changed_floor_ref])

    with pytest.raises(ArtifactChecksumError, match="checksum"):
        RegistrationTargetResolver(artifact_resolver, max_collision_glb_bytes=1_000_000).resolve(request)


def test_rechecks_exact_geometry_bytes(tmp_path: Path) -> None:
    artifact_resolver, geometry_ref, floor_ref = _fixture(tmp_path)
    changed_geometry_ref = geometry_ref.model_copy(update={"artifact_checksum": _checksum("different-geometry")})
    request = _request(changed_geometry_ref, [floor_ref])

    with pytest.raises(ArtifactChecksumError, match="checksum"):
        RegistrationTargetResolver(artifact_resolver, max_collision_glb_bytes=1_000_000).resolve(request)


def test_rejects_floor_evidence_from_another_same_job_source(tmp_path: Path) -> None:
    artifact_resolver, geometry_ref, _ = _fixture(tmp_path)
    other_source_ref = ProductArtifactRef.model_validate(
        geometry_ref.source_provenance["preprocessing_provenance"]["details"]["master"]
    ).model_copy(update={"artifact_checksum": _checksum("different-master")})

    def publish(reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        path = artifact_resolver.resolve(reference.artifact_uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return reference

    wrong_floor_ref, _ = publish_floor_fit_evidence(_JOB, other_source_ref, _floor_model(), publish)
    request = _request(geometry_ref, [wrong_floor_ref])

    with pytest.raises(RegistrationTargetResolutionError, match="not bound to the exact RGB geometry lineage"):
        RegistrationTargetResolver(artifact_resolver, max_collision_glb_bytes=1_000_000).resolve(request)
