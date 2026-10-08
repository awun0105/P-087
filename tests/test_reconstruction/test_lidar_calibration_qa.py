"""Sensor-package calibration QA is fail-closed until projection evidence is scored."""

import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.coordinates import Transform
from src.models.contracts.input_assembly import ClockRelation, DistanceUnit, EvidenceProvenance, EvidenceValue
from src.models.contracts.lidar_calibration_qa import (
    LidarCalibrationFindingCode,
    LidarCalibrationFrameObservation,
    LidarCalibrationObservability,
    LidarCalibrationQAResult,
    seal_lidar_calibration_qa_config,
)
from src.services.reconstruction.lidar.calibration_qa import (
    LidarCalibrationQAInput,
    evaluate_lidar_calibration_qa,
    is_sensor_package_collision_eligible,
)
from src.services.reconstruction.lidar.package import (
    CAMERA_FRAME,
    SENSOR_FRAME,
    CameraCalibration,
    LidarPackageRecord,
)

JOB_ID = "job-lidar-qa"
IDENTITY = (0.0, 0.0, 0.0, 1.0)


def _ref(artifact_type: str, name: str, checksum_char: str = "a") -> ProductArtifactRef:
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{JOB_ID}/qa/{name}",
        artifact_checksum=f"sha256:{checksum_char * 64}",
        data_class=ArtifactDataClass.DERIVED,
        producer_stage="ST-LIDAR-INGEST",
        job_id=JOB_ID,
    )


def _transform(parent: str = SENSOR_FRAME, local: str = CAMERA_FRAME) -> Transform:
    return Transform(
        parent_frame=parent, local_frame=local, translation_xyz=(0.1, 0.0, 0.05), rotation_quaternion_xyzw=IDENTITY
    )


def _record(transform: Transform | None = None) -> LidarPackageRecord:
    return LidarPackageRecord(
        job_id=JOB_ID,
        kind="registered_lidar",
        trajectory_origin="supplied",
        pose_count=6,
        trajectory_ref=_ref("LidarTrajectory", "trajectory.txt"),
        frame_times_ref=_ref("LidarFrameTimes", "frame_times.txt", "b"),
        calibration_ref=_ref("LidarCalibrationSource", "calibration.txt", "c"),
        sensor_from_camera=transform or _transform(),
        camera=CameraCalibration(
            width=640,
            height=480,
            fx=500,
            fy=500,
            cx=320,
            cy=240,
            distortion=(0.0, 0.0, 0.0, 0.0),
            distortion_status="declared",
        ),
        lidar_geometry_ref=_ref("LiDARGeometryArtifact", "cloud.ply", "d"),
        lidar_metadata_ref=_ref("LiDARGeometryMetadata", "metadata.json", "e"),
        point_count=2000,
        floor_z_m=0,
        floor_support_points=600,
        record_checksum=f"sha256:{'f' * 64}",
    )


def _config():
    return seal_lidar_calibration_qa_config(
        profile_id="synthetic-s1-profile",
        minimum_sampled_frames=3,
        minimum_matched_frames=3,
        minimum_overlapping_frames=3,
        minimum_projected_points_per_frame=20,
        minimum_overlap_fraction=0.25,
        maximum_timestamp_residual_sec=0.01,
    )


def _observations(*, count: int = 4, overlap_points: int = 20) -> list[LidarCalibrationFrameObservation]:
    return [
        LidarCalibrationFrameObservation(
            rgb_frame_id=index,
            rgb_timestamp_sec=index * 0.1,
            lidar_pose_id=index,
            lidar_timestamp_sec=index * 0.1,
            projected_point_count=40,
            overlap_point_count=overlap_points,
        )
        for index in range(count)
    ]


def _input(
    *,
    record: LidarPackageRecord | None = None,
    coordinate_unit: DistanceUnit | None = DistanceUnit.METER,
    timestamp_unit: str | None = "seconds",
    clock_relation: ClockRelation | None = ClockRelation.SAME_CLOCK,
    offset: float | None = 0.0,
    camera: CameraCalibration | None = None,
    intrinsics_ref: ProductArtifactRef | None = None,
    missing_camera: bool = False,
    missing_intrinsics_ref: bool = False,
    observations: list[LidarCalibrationFrameObservation] | None = None,
) -> LidarCalibrationQAInput:
    package = record or _record()
    selected_camera = None if missing_camera else camera or package.camera
    selected_intrinsics_ref = (
        None if missing_intrinsics_ref else intrinsics_ref or _ref("CameraIntrinsics", "intrinsics.json", "9")
    )
    return LidarCalibrationQAInput(
        package_ref=_ref("LidarPackageRecord", "package.json", "8"),
        package=package,
        rgb_frame_set_ref=_ref("NormalizedRGBFrameSet", "rgb-frame-set.json", "7"),
        camera=selected_camera,
        intrinsics_ref=selected_intrinsics_ref,
        coordinate_unit=(
            EvidenceValue(value=coordinate_unit, provenance=EvidenceProvenance.DECLARED)
            if coordinate_unit is not None
            else None
        ),
        timestamp_unit=timestamp_unit,
        clock_relation=(
            EvidenceValue(value=clock_relation, provenance=EvidenceProvenance.DECLARED)
            if clock_relation is not None
            else None
        ),
        clock_offset_seconds=(
            EvidenceValue(value=offset, provenance=EvidenceProvenance.DECLARED) if offset is not None else None
        ),
        observations=observations if observations is not None else _observations(),
    )


def _report(**kwargs):
    return evaluate_lidar_calibration_qa(_input(**kwargs), _config())


def test_sufficient_observation_summary_stays_inconclusive_until_projection_scoring() -> None:
    report = _report()

    assert report.result == LidarCalibrationQAResult.INCONCLUSIVE
    assert report.observability == LidarCalibrationObservability.READY_FOR_SCORING
    assert report.sampled_rgb_frame_ids == [0, 1, 2, 3]
    assert report.matched_lidar_pose_ids == [0, 1, 2, 3]
    assert report.calibration_checksum == report.calibration_ref.artifact_checksum
    assert report.timing_checksum == report.timing_ref.artifact_checksum
    assert report.intrinsics_checksum == report.intrinsics_ref.artifact_checksum
    assert LidarCalibrationFindingCode.PROJECTION_SCORING_PENDING in {finding.code for finding in report.findings}
    assert not is_sensor_package_collision_eligible(report)


def test_reversed_transform_direction_is_structural_failure() -> None:
    report = _report(record=_record(_transform(CAMERA_FRAME, SENSOR_FRAME)))

    assert report.result == LidarCalibrationQAResult.FAIL
    assert LidarCalibrationFindingCode.TRANSFORM_DIRECTION_INVALID in {finding.code for finding in report.findings}


def test_non_meter_calibration_unit_is_rejected_without_magnitude_guessing() -> None:
    report = _report(coordinate_unit=DistanceUnit.MILLIMETER)

    assert report.result == LidarCalibrationQAResult.FAIL
    assert LidarCalibrationFindingCode.TRANSLATION_UNIT_UNSUPPORTED in {finding.code for finding in report.findings}


@pytest.mark.parametrize(
    "translation,quaternion,code",
    [
        ((float("nan"), 0.0, 0.0), IDENTITY, LidarCalibrationFindingCode.TRANSFORM_NONFINITE),
        ((0.1, 0.0, 0.0), (0.0, 0.0, 0.0, 2.0), LidarCalibrationFindingCode.TRANSFORM_NOT_SE3),
    ],
)
def test_corrupt_transform_is_reported_as_structural_failure(translation, quaternion, code) -> None:
    corrupted = Transform.model_construct(
        parent_frame=SENSOR_FRAME,
        local_frame=CAMERA_FRAME,
        translation_xyz=translation,
        rotation_quaternion_xyzw=quaternion,
        semantics="parent_from_local",
        quaternion_order="xyzw",
        angle_unit="radian",
    )
    record = _record().model_copy(update={"sensor_from_camera": corrupted})
    report = _report(record=record)

    assert report.result == LidarCalibrationQAResult.FAIL
    assert code in {finding.code for finding in report.findings}


def test_missing_camera_distortion_and_clock_offset_are_inconclusive() -> None:
    camera = CameraCalibration(width=640, height=480, fx=500, fy=500, cx=320, cy=240, distortion_status="missing")
    report = _report(camera=camera, offset=None)
    findings = {finding.code for finding in report.findings}

    assert report.result == LidarCalibrationQAResult.INCONCLUSIVE
    assert LidarCalibrationFindingCode.DISTORTION_UNAVAILABLE in findings
    assert LidarCalibrationFindingCode.CLOCK_OFFSET_MISSING in findings
    assert not is_sensor_package_collision_eligible(report)


def test_missing_coordinate_unit_is_inconclusive() -> None:
    report = _report(coordinate_unit=None)

    assert report.result == LidarCalibrationQAResult.INCONCLUSIVE
    assert LidarCalibrationFindingCode.TRANSLATION_UNIT_MISSING in {finding.code for finding in report.findings}


def test_missing_intrinsics_is_inconclusive() -> None:
    report = _report(missing_camera=True, missing_intrinsics_ref=True)
    findings = {finding.code for finding in report.findings}

    assert report.result == LidarCalibrationQAResult.INCONCLUSIVE
    assert LidarCalibrationFindingCode.CAMERA_INTRINSICS_MISSING in findings


def test_unsorted_sample_timestamps_are_rejected() -> None:
    rows = _observations()
    rows[1] = rows[1].model_copy(update={"rgb_timestamp_sec": 0.3, "lidar_timestamp_sec": 0.3})
    rows[2] = rows[2].model_copy(update={"rgb_timestamp_sec": 0.2, "lidar_timestamp_sec": 0.2})
    report = _report(observations=rows)

    assert report.result == LidarCalibrationQAResult.FAIL
    assert LidarCalibrationFindingCode.TIMESTAMP_ORDER_INVALID in {finding.code for finding in report.findings}


@pytest.mark.parametrize(
    "rows,expected_code",
    [
        (_observations(count=2), LidarCalibrationFindingCode.INSUFFICIENT_SAMPLED_FRAMES),
        (_observations(overlap_points=0), LidarCalibrationFindingCode.INSUFFICIENT_OVERLAP),
    ],
)
def test_sparse_or_no_overlap_frames_remain_inconclusive(rows, expected_code) -> None:
    report = _report(observations=rows)

    assert report.result == LidarCalibrationQAResult.INCONCLUSIVE
    assert expected_code in {finding.code for finding in report.findings}
    assert not is_sensor_package_collision_eligible(report)


def test_timestamp_pairs_outside_the_profile_are_rejected() -> None:
    rows = _observations()
    rows[2] = rows[2].model_copy(update={"lidar_timestamp_sec": 0.25})
    report = _report(observations=rows)

    assert report.result == LidarCalibrationQAResult.FAIL
    assert LidarCalibrationFindingCode.TIMESTAMP_RESIDUAL_EXCEEDED in {finding.code for finding in report.findings}


def test_overlap_without_matched_pose_does_not_count_as_calibration_observability() -> None:
    rows = [row.model_copy(update={"lidar_pose_id": None, "lidar_timestamp_sec": None}) for row in _observations()]
    report = _report(observations=rows)
    findings = {finding.code for finding in report.findings}

    assert report.result == LidarCalibrationQAResult.INCONCLUSIVE
    assert report.matched_frame_count == 0
    assert report.projected_point_count == 0
    assert LidarCalibrationFindingCode.INSUFFICIENT_MATCHED_FRAMES in findings
    assert LidarCalibrationFindingCode.INSUFFICIENT_OVERLAP in findings


def test_package_record_ref_must_match_package_job() -> None:
    inputs = _input()
    wrong_ref = inputs.package_ref.model_copy(update={"job_id": "other-job"})
    report = evaluate_lidar_calibration_qa(inputs.model_copy(update={"package_ref": wrong_ref}), _config())

    assert report.result == LidarCalibrationQAResult.FAIL
    assert LidarCalibrationFindingCode.PACKAGE_REFERENCE_INVALID in {finding.code for finding in report.findings}


def test_legacy_package_without_calibration_ref_remains_readable_but_unqualified() -> None:
    record = _record().model_copy(update={"schema_version": "1.0", "calibration_ref": None})
    report = _report(record=record)

    assert report.result == LidarCalibrationQAResult.INCONCLUSIVE
    assert report.calibration_ref is None
    assert LidarCalibrationFindingCode.CALIBRATION_SOURCE_MISSING in {finding.code for finding in report.findings}
