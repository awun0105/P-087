"""Source eligibility binds LiDAR QA and geometry before collision construction."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import numpy as np
from pydantic import BaseModel

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.collision_quality import (
    CollisionInputMode,
    LidarAlignedPointCloudEvidence,
    LidarSelfMaskEvidence,
)
from src.models.contracts.coordinates import CoordinateSystem, MetricScale, Transform
from src.models.contracts.floor_model import FloorFitEvidence, FloorFitProfile, FloorPrior
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.lidar_calibration_qa import (
    LidarCalibrationObservability,
    LidarCalibrationQAResult,
    seal_lidar_calibration_qa_config,
    seal_lidar_calibration_qa_report,
)
from src.models.contracts.lidar_projection_qa import (
    LidarProjectionDiagnosticCode,
    seal_lidar_calibration_projection_config,
    seal_lidar_calibration_projection_evidence,
)
from src.models.contracts.manifests import InputConfiguration, StageId
from src.models.contracts.reconstruction import AlignmentRecord, ReconstructionBundle
from src.services.reconstruction.adapters.lidar_collision import LidarCollisionProfile
from src.services.reconstruction.lidar.collision_eligibility import (
    CollisionEligibilityBlockerCode,
    LidarCollisionEligibilityInputs,
    evaluate_lidar_collision_eligibility,
)
from src.services.reconstruction.lidar.package import (
    CAMERA_FRAME,
    SENSOR_FRAME,
    CameraCalibration,
    LidarPackageRecord,
)
from src.services.scene.floor_model import fit_floor_model, point_cloud_checksum

JOB_ID = "job-lidar-eligibility"
IDENTITY = (0.0, 0.0, 0.0, 1.0)


def _ref(
    name: str,
    artifact_type: str,
    stage: StageId | str,
    checksum: str = "a",
) -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{JOB_ID}/{name}",
        artifact_checksum="sha256:" + checksum * 64,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=stage,
        job_id=JOB_ID,
    )


def _document_ref(model: BaseModel, artifact_type: str, stage: StageId, name: str) -> ProductArtifactRef:
    payload = model.model_dump_json(indent=2).encode("utf-8") + b"\n"
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version=getattr(model, "schema_version", "1.0"),
        artifact_uri=f"artifact://jobs/{JOB_ID}/{name}",
        artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=stage,
        job_id=JOB_ID,
    )


def _source_points() -> np.ndarray:
    floor = np.asarray([(x, y, 0.0) for x in np.linspace(-1, 1, 9) for y in np.linspace(-1, 1, 9)])
    return np.vstack((floor, np.asarray([(0.0, 0.0, 0.1)]))).astype(np.float64)


def _inputs(
    *,
    input_mode: CollisionInputMode = CollisionInputMode.LIDAR_SENSOR_PACKAGE,
    include_projection: bool = True,
    include_floor: bool = True,
    include_self_mask: bool = True,
) -> LidarCollisionEligibilityInputs:
    points = _source_points()
    point_checksum = point_cloud_checksum(points)
    geometry_ref = _ref("lidar/geometry.ply", "LiDARGeometryArtifact", StageId.LIDAR_INGEST, "1")
    rgb_geometry_ref = _ref("rgb/geometry.glb", "RgbGeometry", StageId.RGB_GEOMETRY, "2")
    lineage = {"dependencies": [], "ground_truth_assisted": False, "details": {}}
    geometry_ref = geometry_ref.model_copy(update={"source_provenance": lineage})
    trajectory_ref = _ref("lidar/trajectory.tum", "LidarTrajectory", StageId.LIDAR_INGEST, "3")
    timing_ref = _ref("lidar/frame_times.txt", "LidarFrameTimes", StageId.LIDAR_INGEST, "4")
    calibration_ref = _ref("lidar/calibration.json", "LidarCalibrationSource", StageId.LIDAR_INGEST, "5")
    metadata_ref = _ref("lidar/metadata.json", "LiDARGeometryMetadata", StageId.LIDAR_INGEST, "6")
    camera = CameraCalibration(
        width=640,
        height=480,
        fx=500,
        fy=500,
        cx=320,
        cy=240,
        distortion=(0.0, 0.0, 0.0, 0.0),
        distortion_status="declared",
    )
    package = LidarPackageRecord(
        job_id=JOB_ID,
        kind="lidar_scan_sequence",
        trajectory_origin="supplied",
        pose_count=6,
        trajectory_ref=trajectory_ref,
        frame_times_ref=timing_ref,
        calibration_ref=calibration_ref,
        sensor_from_camera=Transform(
            parent_frame=SENSOR_FRAME,
            local_frame=CAMERA_FRAME,
            translation_xyz=(0.1, 0.0, 0.05),
            rotation_quaternion_xyzw=IDENTITY,
        ),
        camera=camera,
        lidar_geometry_ref=geometry_ref,
        lidar_metadata_ref=metadata_ref,
        point_count=len(points),
        floor_z_m=0.0,
        floor_support_points=500,
        record_checksum="sha256:" + "0" * 64,
    )
    package = package.model_copy(update={"record_checksum": canonical_content_checksum(package, "record_checksum")})
    package_ref = _document_ref(package, "LidarPackageRecord", StageId.LIDAR_INGEST, "lidar/package.json")
    alignment = AlignmentRecord(
        artifact_type="AlignmentRecord",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{JOB_ID}/alignment/record.json",
        artifact_checksum="sha256:" + "7" * 64,
        producer_stage=StageId.RGB_LIDAR_ALIGN,
        job_id=JOB_ID,
        source_lidar_checksum=geometry_ref.artifact_checksum,
        target_rgb_geometry_checksum=rgb_geometry_ref.artifact_checksum,
        transform_target_from_source=Transform(
            parent_frame="world",
            local_frame="lidar_map",
            translation_xyz=(0, 0, 0),
            rotation_quaternion_xyzw=IDENTITY,
        ),
        status="CONFIRMED",
        method="test_confirmed_alignment",
        evidence_refs=[_ref("alignment/review.json", "AlignmentReview", StageId.RGB_LIDAR_ALIGN, "8")],
        provenance={"ground_truth_assisted": False},
    )
    alignment_ref = ProductArtifactRef(
        artifact_type=alignment.artifact_type,
        schema_version=alignment.schema_version,
        artifact_uri=alignment.artifact_uri,
        artifact_checksum=alignment.artifact_checksum,
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=alignment.producer_stage,
        job_id=alignment.job_id,
        source_provenance=alignment.provenance,
    )
    bundle = ReconstructionBundle(
        artifact_type="ReconstructionBundle",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{JOB_ID}/bundle/reconstruction.json",
        artifact_checksum="sha256:" + "9" * 64,
        producer_stage=StageId.METRIC_CANONICALIZE,
        job_id=JOB_ID,
        source_input_checksum="sha256:" + "a" * 64,
        input_configuration=InputConfiguration(
            rgb_present=True,
            registered_lidar_present=True,
            declared_same_scene=True,
        ),
        coordinate_system=CoordinateSystem(),
        metric_scale=MetricScale(status="CONFIRMED", meters_per_unit=1.0),
        rgb_frame_refs=[_ref("rgb/frame.png", "RGBFrame", StageId.FRAME_EXTRACT, "b")],
        camera_pose_refs=[_ref("rgb/poses.json", "CameraPoseArtifact", StageId.CAMERA_POSE, "c")],
        visual_artifact_ref=_ref("rgb/visual.ply", "VisualArtifact", StageId.VISUAL_RECON, "d"),
        rgb_geometry_ref=rgb_geometry_ref,
        lidar_geometry_ref=geometry_ref,
        alignment_record=alignment,
        canonical_geometry_ref=rgb_geometry_ref,
        provenance={"ground_truth_assisted": False},
    )
    aligned_point_cloud = LidarAlignedPointCloudEvidence(
        job_id=JOB_ID,
        source_geometry_ref=geometry_ref,
        alignment_ref=alignment_ref,
        point_cloud_checksum=point_checksum,
        point_count=len(points),
    )
    aligned_point_cloud_ref = _document_ref(
        aligned_point_cloud,
        "LidarAlignedPointCloudEvidence",
        StageId.COLLIDER,
        "collision/aligned-points.json",
    )

    qa_profile = seal_lidar_calibration_qa_config(
        profile_id="audit-13-diagnostic-fixture",
        minimum_sampled_frames=3,
        minimum_matched_frames=3,
        minimum_overlapping_frames=2,
        minimum_projected_points_per_frame=10,
        minimum_overlap_fraction=0.1,
        maximum_timestamp_residual_sec=0.05,
    )
    projection_profile = seal_lidar_calibration_projection_config(
        profile_id="audit-13-projection-fixture",
        edge_distance_threshold_px=4,
        minimum_edge_pixels=50,
        maximum_points_per_frame=5000,
        maximum_edge_pixels_per_frame=5000,
        maximum_overlay_samples_per_frame=64,
        minimum_edge_orientation_bins=2,
        minimum_edge_span_fraction=0.2,
        maximum_frame_median_spread_px=8,
    )
    projection = seal_lidar_calibration_projection_evidence(
        package_ref=package_ref,
        calibration_ref=calibration_ref,
        trajectory_ref=trajectory_ref,
        timing_ref=timing_ref,
        intrinsics_ref=_ref("rgb/intrinsics.json", "CameraIntrinsics", StageId.CAMERA_POSE, "e"),
        rgb_frame_set_ref=_ref("rgb/frame-set.json", "NormalizedRGBFrameSet", StageId.FRAME_EXTRACT, "f"),
        qa_profile=qa_profile,
        projection_profile=projection_profile,
        projection_model=None,
        frames=[],
        scoring_status="INCONCLUSIVE",
        qualification_status="diagnostic_only",
        diagnostic_reasons=[LidarProjectionDiagnosticCode.CAMERA_PIXEL_BASIS_UNKNOWN],
        observable_frame_count=0,
        projected_point_count=0,
        overlap_point_count=0,
        overlap_fraction=None,
        median_frame_error_px=None,
        p90_frame_error_px=None,
        frame_median_spread_px=None,
    )
    projection_ref = _document_ref(
        projection,
        "LidarCalibrationProjectionEvidence",
        StageId.LIDAR_CALIBRATION_QA,
        "lidar-calibration-qa/projection-evidence.json",
    )
    report = seal_lidar_calibration_qa_report(
        package_ref=package_ref,
        calibration_ref=calibration_ref,
        trajectory_ref=trajectory_ref,
        timing_ref=timing_ref,
        intrinsics_ref=projection.intrinsics_ref,
        rgb_frame_set_ref=projection.rgb_frame_set_ref,
        profile=qa_profile,
        input_checksum=package_ref.artifact_checksum,
        calibration_checksum=calibration_ref.artifact_checksum,
        timing_checksum=timing_ref.artifact_checksum,
        intrinsics_checksum=projection.intrinsics_ref.artifact_checksum,
        config_checksum=qa_profile.config_checksum,
        coordinate_unit="m",
        timestamp_unit="seconds",
        clock_relation="same_clock",
        clock_offset_seconds=0.0,
        sampled_rgb_frame_ids=[0, 1, 2],
        matched_lidar_pose_ids=[0, 1, 2],
        sampled_frame_count=3,
        matched_frame_count=3,
        trajectory_pose_count=package.pose_count,
        observable_frame_count=2,
        projected_point_count=200,
        overlap_point_count=100,
        overlap_fraction=0.5,
        maximum_timestamp_residual_sec=0.001,
        observability=LidarCalibrationObservability.READY_FOR_SCORING,
        result=LidarCalibrationQAResult.PASS,
        findings=[],
        overlay_refs=[],
        diagnostic_projection_ref=projection_ref,
        projection_evidence_ref=projection_ref,
    )
    qa_ref = _document_ref(
        report, "LidarCalibrationQAReport", StageId.LIDAR_CALIBRATION_QA, "lidar-calibration-qa/report.json"
    )

    floor_profile = FloorFitProfile(min_coverage_area_m2=0.5)
    floor_model = fit_floor_model(
        points,
        point_checksum,
        FloorPrior(up_direction_world=(0.0, 0.0, 1.0), point_on_floor_world=(0.0, 0.0, 0.0)),
        floor_profile,
    )
    floor_evidence = FloorFitEvidence(
        job_id=JOB_ID,
        source_artifact_ref=aligned_point_cloud_ref,
        point_cloud_checksum=point_checksum,
        floor_model=floor_model,
    )
    floor_ref = _document_ref(floor_evidence, "FloorFitEvidence", StageId.OBJECT_EXTRACT, "floor/evidence.json")
    robot_profile_ref = _ref("profiles/robot.json", "RobotProfile", StageId.CANDIDATE_BUILD, "1")
    self_mask = LidarSelfMaskEvidence(
        job_id=JOB_ID,
        package_ref=package_ref,
        source_geometry_ref=geometry_ref,
        alignment_ref=alignment_ref,
        aligned_point_cloud_ref=aligned_point_cloud_ref,
        trajectory_ref=trajectory_ref,
        robot_profile_ref=robot_profile_ref,
        source_point_checksum=point_checksum,
        point_count=len(points),
        mask_binding_checksum="sha256:" + "2" * 64,
        masked_point_count=1,
        covered_pose_count=package.pose_count,
        total_pose_count=package.pose_count,
        algorithm="sensor_frame_robot_envelope_v1",
    )
    self_mask_ref = _document_ref(self_mask, "LidarSelfMaskEvidence", StageId.COLLIDER, "lidar/self-mask-evidence.json")
    return LidarCollisionEligibilityInputs(
        input_mode=input_mode,
        bundle=bundle,
        package_ref=package_ref,
        package=package,
        calibration_qa_ref=qa_ref,
        calibration_qa=report,
        projection_evidence_ref=projection_ref if include_projection else None,
        projection_evidence=projection if include_projection else None,
        aligned_point_cloud_ref=aligned_point_cloud_ref,
        aligned_point_cloud=aligned_point_cloud,
        floor_evidence_ref=floor_ref if include_floor else None,
        floor_evidence=floor_evidence if include_floor else None,
        self_mask_evidence_ref=self_mask_ref if include_self_mask else None,
        self_mask_evidence=self_mask if include_self_mask else None,
        profile=LidarCollisionProfile(profile_id="audit-12-test", voxel_m=0.1),
    )


def test_diagnostic_projection_blocks_candidate_even_if_report_claims_pass() -> None:
    assessment = evaluate_lidar_collision_eligibility(_inputs())

    assert assessment.state == "blocked"
    codes = {item.code for item in assessment.blockers}
    assert CollisionEligibilityBlockerCode.PROJECTION_EVIDENCE_NOT_SCORED in codes
    assert CollisionEligibilityBlockerCode.PROJECTION_EVIDENCE_DIAGNOSTIC_ONLY in codes
    assert CollisionEligibilityBlockerCode.CALIBRATION_QA_NOT_PASS in codes
    assert assessment.source_geometry_ref is not None
    assert assessment.profile_checksum == _inputs().profile.checksum()


def test_missing_floor_and_self_mask_are_explicit_blockers() -> None:
    assessment = evaluate_lidar_collision_eligibility(_inputs(include_floor=False, include_self_mask=False))

    codes = {item.code for item in assessment.blockers}
    assert CollisionEligibilityBlockerCode.FLOOR_EVIDENCE_MISSING in codes
    assert CollisionEligibilityBlockerCode.SELF_MASK_EVIDENCE_MISSING in codes


def test_missing_calibration_and_timing_qa_returns_blocker() -> None:
    inputs = _inputs()
    assessment = evaluate_lidar_collision_eligibility(
        replace(
            inputs,
            calibration_qa_ref=None,
            calibration_qa=None,
            projection_evidence_ref=None,
            projection_evidence=None,
        )
    )

    assert CollisionEligibilityBlockerCode.CALIBRATION_QA_MISSING in {item.code for item in assessment.blockers}


def test_calibration_qa_for_another_calibration_is_blocked() -> None:
    inputs = _inputs()
    assert inputs.calibration_qa is not None
    mismatched_report = inputs.calibration_qa.model_copy(
        update={
            "calibration_ref": _ref("lidar/other-calibration.json", "LidarCalibrationSource", StageId.LIDAR_INGEST, "d")
        }
    )
    mismatched_report_ref = _document_ref(
        mismatched_report,
        "LidarCalibrationQAReport",
        StageId.LIDAR_CALIBRATION_QA,
        "lidar-calibration-qa/mismatched-report.json",
    )
    assessment = evaluate_lidar_collision_eligibility(
        replace(inputs, calibration_qa=mismatched_report, calibration_qa_ref=mismatched_report_ref)
    )

    assert CollisionEligibilityBlockerCode.CALIBRATION_QA_SOURCE_MISMATCH in {item.code for item in assessment.blockers}


def test_stale_calibration_report_ref_returns_blocker() -> None:
    inputs = _inputs()
    assert inputs.calibration_qa_ref is not None
    stale_ref = inputs.calibration_qa_ref.model_copy(update={"artifact_checksum": "sha256:" + "0" * 64})
    assessment = evaluate_lidar_collision_eligibility(replace(inputs, calibration_qa_ref=stale_ref))

    assert CollisionEligibilityBlockerCode.CALIBRATION_QA_REFERENCE_INVALID in {
        item.code for item in assessment.blockers
    }


def test_floor_and_self_mask_cannot_reuse_a_receipt_from_another_alignment() -> None:
    inputs = _inputs()
    assert inputs.aligned_point_cloud is not None
    stale_alignment = _ref("alignment/stale.json", "AlignmentRecord", StageId.RGB_LIDAR_ALIGN, "c")
    stale_points = inputs.aligned_point_cloud.model_copy(update={"alignment_ref": stale_alignment})
    stale_points_ref = _document_ref(
        stale_points,
        "LidarAlignedPointCloudEvidence",
        StageId.COLLIDER,
        "collision/stale-aligned-points.json",
    )
    assessment = evaluate_lidar_collision_eligibility(
        replace(inputs, aligned_point_cloud=stale_points, aligned_point_cloud_ref=stale_points_ref)
    )

    codes = {item.code for item in assessment.blockers}
    assert CollisionEligibilityBlockerCode.ALIGNED_POINT_CLOUD_EVIDENCE_SOURCE_MISMATCH in codes
    assert CollisionEligibilityBlockerCode.FLOOR_EVIDENCE_SOURCE_MISMATCH in codes
    assert CollisionEligibilityBlockerCode.SELF_MASK_EVIDENCE_SOURCE_MISMATCH in codes


def test_registered_map_uses_registration_qa_route_not_sensor_package_qa() -> None:
    assessment = evaluate_lidar_collision_eligibility(_inputs(input_mode=CollisionInputMode.LIDAR_REGISTERED_MAP))

    assert assessment.state == "blocked"
    assert CollisionEligibilityBlockerCode.REGISTERED_MAP_QA_UNAVAILABLE in {item.code for item in assessment.blockers}


def test_missing_collision_profile_is_a_blocker() -> None:
    assessment = evaluate_lidar_collision_eligibility(replace(_inputs(), profile=None))

    assert CollisionEligibilityBlockerCode.COLLISION_PROFILE_MISSING in {item.code for item in assessment.blockers}
