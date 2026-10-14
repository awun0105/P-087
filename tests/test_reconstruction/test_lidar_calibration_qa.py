"""Sensor-package calibration QA is fail-closed until projection evidence is scored."""

import hashlib

import numpy as np
import pytest
from pydantic import ValidationError

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
from src.models.contracts.lidar_projection_qa import (
    LidarCalibrationProjectionEvidence,
    LidarProjectionDiagnosticCode,
    seal_lidar_calibration_projection_config,
)
from src.services.reconstruction.alignment.similarity import rotation_matrix
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
from src.services.reconstruction.lidar.projection_qa import (
    LidarCalibrationProjectionFrame,
    build_lidar_calibration_projection_model,
    score_lidar_calibration_projection,
)
from tests.test_reconstruction.test_rec03_guided import _rotated_sar_video_verification

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
    report = _report(camera=camera, offset=None, clock_relation=ClockRelation.KNOWN_OFFSET)
    findings = {finding.code for finding in report.findings}

    assert report.result == LidarCalibrationQAResult.INCONCLUSIVE
    assert LidarCalibrationFindingCode.DISTORTION_UNAVAILABLE in findings
    assert LidarCalibrationFindingCode.CLOCK_OFFSET_MISSING in findings
    assert not is_sensor_package_collision_eligible(report)


def test_explicit_same_clock_relation_means_zero_without_offset_payload() -> None:
    report = _report(offset=None, clock_relation=ClockRelation.SAME_CLOCK)
    findings = {finding.code for finding in report.findings}

    assert report.clock_offset_seconds == 0.0
    assert LidarCalibrationFindingCode.CLOCK_OFFSET_MISSING not in findings
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


def _projection_profile(**overrides):
    payload = {
        "profile_id": "synthetic-projection-profile",
        "edge_distance_threshold_px": 3.0,
        "minimum_edge_pixels": 30,
        "maximum_points_per_frame": 5_000,
        "maximum_edge_pixels_per_frame": 5_000,
        "maximum_overlay_samples_per_frame": 64,
        "minimum_edge_orientation_bins": 2,
        "minimum_edge_span_fraction": 0.25,
        "maximum_frame_median_spread_px": 5.0,
    }
    return seal_lidar_calibration_projection_config(**(payload | overrides))


def _projection_fixture(
    *,
    pattern: str = "grid",
    sparse_point_count: int | None = None,
    shifted_frame_index: int | None = None,
    point_shift: tuple[float, float, float] = (0.0, 0.0, 0.0),
    timestamp_shift: float = 0.0,
    duplicate_far_point: bool = False,
):
    camera = CameraCalibration(
        width=320,
        height=240,
        fx=200,
        fy=200,
        cx=160,
        cy=120,
        distortion=(0.0, 0.0, 0.0, 0.0),
        distortion_status="declared",
    )
    true_transform = Transform(
        parent_frame=SENSOR_FRAME,
        local_frame=CAMERA_FRAME,
        translation_xyz=(0.17, -0.08, 0.05),
        rotation_quaternion_xyzw=(0.05, -0.08, 0.06, 0.9937303457),
    )

    pixels: list[tuple[int, int]] = []
    normals: list[tuple[float, float]] = []
    camera_points: list[tuple[float, float, float]] = []
    verticals, horizontals = (40, 160, 280), (40, 120, 200)
    for u in verticals:
        for v in range(12, 229, 4):
            if any(abs(v - y) < 8 for y in horizontals):
                continue
            pixels.append((u, v))
            normals.append((1.0, 0.0))
    if pattern == "grid":
        for v in horizontals:
            for u in range(12, 309, 4):
                if any(abs(u - x) < 8 for x in verticals):
                    continue
                pixels.append((u, v))
                normals.append((0.0, 1.0))
    for u, v in pixels:
        depth = 3.0 + ((u * 7 + v * 11) % 50) / 10.0
        camera_points.append(((u - camera.cx) * depth / camera.fx, (v - camera.cy) * depth / camera.fy, depth))

    points_camera = np.asarray(camera_points, dtype=np.float64)
    true_rotation = rotation_matrix(true_transform.rotation_quaternion_xyzw)
    points_sensor = points_camera @ true_rotation.T + np.asarray(true_transform.translation_xyz)
    edge_pixels = np.asarray(pixels if pattern != "textureless" else [], dtype=np.int32).reshape((-1, 2))
    edge_normals = np.asarray(normals if pattern != "textureless" else [], dtype=np.float64).reshape((-1, 2))
    observations = _observations()
    if timestamp_shift:
        observations[-1] = observations[-1].model_copy(
            update={"rgb_timestamp_sec": observations[-1].rgb_timestamp_sec + timestamp_shift}
        )
    inputs = _input(record=_record(transform=true_transform), camera=camera, observations=observations)
    frames = []
    for index, observation in enumerate(observations):
        frame_points = points_sensor.copy()
        if sparse_point_count is not None:
            frame_points = frame_points[:sparse_point_count]
        if shifted_frame_index == index:
            frame_points += np.asarray(point_shift)
        if duplicate_far_point and index == 0 and len(frame_points):
            # Same sensor ray, farther return: z-buffering must retain only the nearer sample.
            origin = np.asarray(true_transform.translation_xyz)
            frame_points = np.vstack((frame_points, origin + (frame_points[0] - origin) * 2.0))
        frames.append(
            LidarCalibrationProjectionFrame(
                frame_id=observation.rgb_frame_id,
                lidar_pose_id=observation.lidar_pose_id,
                rgb_timestamp_sec=observation.rgb_timestamp_sec,
                lidar_timestamp_sec=observation.lidar_timestamp_sec,
                rgb_frame_checksum="sha256:" + hashlib.sha256(f"rgb-{index}".encode()).hexdigest(),
                lidar_scan_checksum="sha256:"
                + hashlib.sha256(f"lidar-{index}-{shifted_frame_index}".encode()).hexdigest(),
                pixel_basis="prepared_rgb",
                image_width=camera.width,
                image_height=camera.height,
                edge_pixels_xy=edge_pixels,
                edge_normals_xy=edge_normals,
                lidar_points_sensor_m=frame_points,
            )
        )
    return inputs, frames


def _with_extrinsic(inputs: LidarCalibrationQAInput, transform: Transform) -> LidarCalibrationQAInput:
    package = inputs.package.model_copy(update={"sensor_from_camera": transform})
    return inputs.model_copy(update={"package": package})


def _quaternion_product(left, right):
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def _score_projection(inputs, frames, **profile_overrides):
    return score_lidar_calibration_projection(
        inputs,
        _config(),
        _projection_profile(**profile_overrides),
        frames,
        camera_pixel_basis="prepared_rgb",
        rgb_frame_pixel_basis="prepared_rgb",
    )


def test_projection_scoring_records_metrics_and_renderable_overlay_samples() -> None:
    inputs, frames = _projection_fixture()
    report = _score_projection(inputs, frames)

    assert report.scoring_status == "SCORED"
    assert report.qualification_status == "diagnostic_only"
    assert report.observable_frame_count == 4
    assert report.p90_frame_error_px == pytest.approx(0.0, abs=1e-8)
    assert all(frame.overlay_samples for frame in report.frames)
    assert report.frames[0].point_samples_checksum.startswith("sha256:")


def test_projection_refuses_to_pair_camera_and_rgb_from_different_pixel_bases_without_verification() -> None:
    inputs, frames = _projection_fixture()
    report = score_lidar_calibration_projection(
        inputs,
        _config(),
        _projection_profile(),
        frames,
        camera_pixel_basis="source_video",
        rgb_frame_pixel_basis="prepared_rgb",
    )

    assert report.projection_model is None
    assert report.scoring_status == "INCONCLUSIVE"
    assert LidarProjectionDiagnosticCode.CAMERA_PIXEL_BASIS_UNKNOWN in report.diagnostic_reasons
    assert report.frames == []


def test_projection_model_maps_source_camera_to_verified_prepared_rgb_basis() -> None:
    inputs = _input()
    verification = _rotated_sar_video_verification()

    model = build_lidar_calibration_projection_model(
        inputs,
        camera_pixel_basis="source_video",
        rgb_frame_pixel_basis="prepared_rgb",
        video_preparation_verification=verification,
    )

    assert model is not None
    assert model.pixel_basis == "prepared_rgb"
    assert (model.width, model.height) == (240, 480)
    assert model.pixel_transform_checksum is not None


def test_missing_camera_is_reported_as_intrinsics_missing_without_false_pixel_basis_error() -> None:
    inputs, frames = _projection_fixture()
    report = _score_projection(inputs.model_copy(update={"camera": None}), frames)

    assert report.scoring_status == "INCONCLUSIVE"
    assert report.projection_model is None
    assert LidarProjectionDiagnosticCode.CAMERA_INTRINSICS_MISSING in report.diagnostic_reasons
    assert LidarProjectionDiagnosticCode.CAMERA_PIXEL_BASIS_UNKNOWN not in report.diagnostic_reasons


@pytest.mark.parametrize("axis,angle_deg", [(axis, angle) for axis in range(3) for angle in (-5, -1, 1, 5)])
def test_projection_score_separates_known_rotation_perturbations(axis: int, angle_deg: float) -> None:
    inputs, frames = _projection_fixture()
    correct = _score_projection(inputs, frames)
    base_transform = inputs.package.sensor_from_camera
    half_angle = np.deg2rad(angle_deg) / 2
    delta = [0.0, 0.0, 0.0, float(np.cos(half_angle))]
    delta[axis] = float(np.sin(half_angle))
    wrong_transform = Transform(
        parent_frame=SENSOR_FRAME,
        local_frame=CAMERA_FRAME,
        translation_xyz=base_transform.translation_xyz,
        rotation_quaternion_xyzw=_quaternion_product(tuple(delta), base_transform.rotation_quaternion_xyzw),
    )
    wrong = _score_projection(_with_extrinsic(inputs, wrong_transform), frames)

    assert wrong.p90_frame_error_px is not None
    assert correct.p90_frame_error_px is not None
    assert wrong.p90_frame_error_px > correct.p90_frame_error_px + 0.25


@pytest.mark.parametrize("axis", range(3))
@pytest.mark.parametrize("sign", (-1.0, 1.0))
def test_projection_score_separates_known_five_centimeter_translation(axis: int, sign: float) -> None:
    inputs, frames = _projection_fixture()
    correct = _score_projection(inputs, frames)
    base_transform = inputs.package.sensor_from_camera
    translation = list(base_transform.translation_xyz)
    translation[axis] += sign * 0.05
    wrong_transform = Transform(
        parent_frame=SENSOR_FRAME,
        local_frame=CAMERA_FRAME,
        translation_xyz=tuple(translation),
        rotation_quaternion_xyzw=base_transform.rotation_quaternion_xyzw,
    )
    wrong = _score_projection(_with_extrinsic(inputs, wrong_transform), frames)

    assert wrong.p90_frame_error_px is not None
    assert correct.p90_frame_error_px is not None
    assert wrong.p90_frame_error_px > correct.p90_frame_error_px + 0.25


@pytest.mark.parametrize(
    "pattern,sparse_point_count,expected",
    [
        ("textureless", None, LidarProjectionDiagnosticCode.NO_EDGE_FEATURES),
        ("wall", None, LidarProjectionDiagnosticCode.EDGE_ORIENTATION_DEGENERATE),
        ("grid", 5, LidarProjectionDiagnosticCode.TOO_FEW_PROJECTED_POINTS),
    ],
)
def test_degenerate_or_sparse_projection_is_inconclusive(pattern, sparse_point_count, expected) -> None:
    inputs, frames = _projection_fixture(pattern=pattern, sparse_point_count=sparse_point_count)
    report = _score_projection(inputs, frames)

    assert report.scoring_status == "INCONCLUSIVE"
    assert expected in {reason for frame in report.frames for reason in frame.diagnostic_reasons}


def test_timestamp_outlier_is_rejected_by_existing_calibration_preflight() -> None:
    inputs, frames = _projection_fixture(timestamp_shift=0.1)
    report = _score_projection(inputs, frames)

    assert report.scoring_status == "INCONCLUSIVE"
    assert LidarProjectionDiagnosticCode.STRUCTURAL_QA_FAILED in report.diagnostic_reasons
    assert report.frames == []


def test_z_buffer_suppresses_farther_returns_at_the_same_projected_pixel() -> None:
    inputs, frames = _projection_fixture(duplicate_far_point=True)
    report = _score_projection(inputs, frames)
    first = report.frames[0]

    assert first.in_frame_point_count == first.visible_projected_point_count + 1


def test_frame_score_variance_keeps_motion_or_timing_confounds_inconclusive() -> None:
    inputs, frames = _projection_fixture(shifted_frame_index=3, point_shift=(0.03, 0.0, 0.0))
    report = _score_projection(inputs, frames, maximum_frame_median_spread_px=0.1)

    assert report.scoring_status == "INCONCLUSIVE"
    assert LidarProjectionDiagnosticCode.CROSS_FRAME_SCORE_VARIANCE in report.diagnostic_reasons


def test_projection_evidence_rejects_tampered_aggregate_counts() -> None:
    inputs, frames = _projection_fixture()
    report = _score_projection(inputs, frames)

    with pytest.raises(ValidationError, match="overlap_point_count must match per-frame"):
        LidarCalibrationProjectionEvidence.model_validate(
            report.model_dump(mode="json") | {"overlap_point_count": report.overlap_point_count + 1}
        )
