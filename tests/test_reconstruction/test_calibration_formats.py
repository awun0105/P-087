"""Parser calibration đa định dạng: cùng một biến đổi vật lý, bốn cách ghi, phải ra cùng một kết quả."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from src.services.reconstruction.inputs.calibration_formats import (
    CalibrationParseError,
    Extrinsic,
    canonical_lidar_camera_json,
    compose_lidar_from_camera,
    detect_format,
    extrinsic_from_matrix,
    looks_like_torwic_text,
    parse_kalibr_camchain,
    parse_lidar_camera_json,
    parse_ros_transform_yaml,
    parse_torwic_text,
)

# Extrinsic thật của TorWIC (`T_cam1_os` trong calibrations.txt), chuẩn hoá để mọi định dạng cùng số.
_RAW_TRANSLATION = (0.12944592, 0.04299934, -0.1137434)
_RAW_QUATERNION = (-0.6116725, 0.39292797, -0.3567415, 0.58668551)
_NORM = math.sqrt(sum(item * item for item in _RAW_QUATERNION))
QUATERNION = tuple(item / _NORM for item in _RAW_QUATERNION)
TRANSLATION = _RAW_TRANSLATION


def _rotation(quaternion: tuple[float, float, float, float]) -> np.ndarray:
    x, y, z, w = quaternion
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _matrix() -> list[list[float]]:
    result = np.eye(4)
    result[:3, :3] = _rotation(QUATERNION)
    result[:3, 3] = TRANSLATION
    return result.tolist()


def _torwic_text() -> str:
    names = ("px", "py", "pz", "qx", "qy", "qz", "qw")
    rows = [f"T_cam1_os.{name}: {value!r}" for name, value in zip(names, (*TRANSLATION, *QUATERNION), strict=True)]
    return "# synthetic: extrinsic thật của TorWIC, quaternion chuẩn hoá\n" + "\n".join(rows) + "\n"


def _json_quaternion() -> str:
    return json.dumps({"lidar_from_camera": {"translation_xyz": list(TRANSLATION), "rotation_xyzw": list(QUATERNION)}})


def _json_matrix() -> str:
    return json.dumps({"lidar_from_camera": {"matrix": _matrix()}})


def _json_inverse() -> str:
    inverse = np.linalg.inv(np.array(_matrix()))
    return json.dumps({"camera_from_lidar": {"matrix": inverse.tolist()}})


def _ros_yaml(*, parent: str, child: str, invert: bool = False) -> str:
    matrix = np.array(_matrix())
    if invert:
        matrix = np.linalg.inv(matrix)
    translation = [float(item) for item in matrix[:3, 3]]
    x, y, z, w = (
        float(item)
        for item in extrinsic_from_matrix(matrix, parent=parent, local=child, source="ros_transform_yaml").rotation_xyzw
    )
    return (
        "# synthetic\n"
        "header:\n"
        f"  frame_id: {parent}\n"
        f"child_frame_id: {child}\n"
        "transform:\n"
        f"  translation: {{x: {translation[0]!r}, y: {translation[1]!r}, z: {translation[2]!r}}}\n"
        f"  rotation: {{x: {x!r}, y: {y!r}, z: {z!r}, w: {w!r}}}\n"
    )


def _assert_same(actual: Extrinsic, *, tolerance: float = 1e-9) -> None:
    assert actual.parent_frame == "lidar" and actual.local_frame == "camera"
    assert np.allclose(actual.translation_xyz, TRANSLATION, atol=tolerance)
    # q và -q là cùng một phép quay: so sánh qua ma trận.
    assert np.allclose(_rotation(actual.rotation_xyzw), _rotation(QUATERNION), atol=tolerance)


# ---------------------------------------------------------------------------
# Phép thử đẳng nghĩa: bốn cách ghi cùng một biến đổi
# ---------------------------------------------------------------------------


def test_torwic_text_reads_the_label_as_lidar_from_camera() -> None:
    assert looks_like_torwic_text(_torwic_text())
    _assert_same(parse_torwic_text(_torwic_text()))


def test_json_quaternion_form_matches() -> None:
    _assert_same(parse_lidar_camera_json(_json_quaternion()))


def test_json_matrix_form_matches() -> None:
    _assert_same(parse_lidar_camera_json(_json_matrix()))


def test_json_declared_in_the_opposite_direction_is_inverted_back() -> None:
    _assert_same(parse_lidar_camera_json(_json_inverse()))


def test_ros_yaml_with_lidar_as_parent_matches() -> None:
    parsed = parse_ros_transform_yaml(_ros_yaml(parent="velodyne", child="cam"), lidar_frame_id="velodyne")
    assert parsed.parent_frame == "velodyne" and parsed.local_frame == "cam"
    assert np.allclose(parsed.translation_xyz, TRANSLATION, atol=1e-9)
    assert np.allclose(_rotation(parsed.rotation_xyzw), _rotation(QUATERNION), atol=1e-9)


def test_ros_yaml_with_lidar_as_child_is_inverted_to_lidar_from_camera() -> None:
    # File ghi `cam` là cha, `velodyne` là con (pose của LiDAR trong camera): chiều ngược.
    text = _ros_yaml(parent="cam", child="velodyne", invert=True)
    parsed = parse_ros_transform_yaml(text, lidar_frame_id="velodyne")
    assert parsed.parent_frame == "velodyne" and parsed.local_frame == "cam"
    assert np.allclose(parsed.translation_xyz, TRANSLATION, atol=1e-9)
    assert np.allclose(_rotation(parsed.rotation_xyzw), _rotation(QUATERNION), atol=1e-9)


# ---------------------------------------------------------------------------
# Từ chối thay vì đoán
# ---------------------------------------------------------------------------


def test_ros_yaml_without_a_declared_lidar_frame_is_refused() -> None:
    with pytest.raises(CalibrationParseError, match="chưa biết frame nào là LiDAR"):
        parse_ros_transform_yaml(_ros_yaml(parent="a", child="b"), lidar_frame_id=None)


def test_ros_yaml_whose_frames_do_not_include_the_lidar_is_refused() -> None:
    with pytest.raises(CalibrationParseError, match="không khớp"):
        parse_ros_transform_yaml(_ros_yaml(parent="a", child="b"), lidar_frame_id="velodyne")


def test_json_with_both_directions_is_refused() -> None:
    both = json.dumps({"lidar_from_camera": {"matrix": _matrix()}, "camera_from_lidar": {"matrix": _matrix()}})
    with pytest.raises(CalibrationParseError, match="chọn một chiều"):
        parse_lidar_camera_json(both)


def test_matrix_that_is_not_a_rotation_is_refused() -> None:
    skewed = _matrix()
    skewed[0][0] = 2.0
    with pytest.raises(CalibrationParseError, match="phép quay hợp lệ"):
        parse_lidar_camera_json(json.dumps({"lidar_from_camera": {"matrix": skewed}}))


def test_unnormalized_quaternion_is_refused_not_repaired() -> None:
    bad = json.dumps({"lidar_from_camera": {"translation_xyz": [0, 0, 0], "rotation_xyzw": [0, 0, 0, 2]}})
    with pytest.raises(CalibrationParseError, match="chưa chuẩn hoá"):
        parse_lidar_camera_json(bad)


@pytest.mark.parametrize(
    "bomb",
    [
        "a: &x [1, 2]\nb: *x\n",
        "a: &1 [x, x]\nb: *1\n",  # tên anchor bắt đầu bằng số: regex cũ bỏ sót
    ],
)
def test_yaml_anchors_and_aliases_are_refused(bomb: str) -> None:
    with pytest.raises(CalibrationParseError, match="anchor/alias"):
        parse_ros_transform_yaml(bomb, lidar_frame_id="velodyne")


def test_non_ascii_anchor_is_refused_by_the_scanner_itself() -> None:
    with pytest.raises(CalibrationParseError):
        parse_ros_transform_yaml("a: &tên [x, x]\nb: *tên\n", lidar_frame_id="velodyne")


def test_ampersand_and_star_in_comments_and_strings_are_not_anchors() -> None:
    text = _ros_yaml(parent="velodyne", child="cam *front") + "# see &imu and *notes\n"
    parsed = parse_ros_transform_yaml(text, lidar_frame_id="velodyne")
    assert parsed.local_frame == "cam *front"


def test_ros_yaml_other_end_must_be_the_declared_camera() -> None:
    text = _ros_yaml(parent="velodyne", child="imu_link")
    with pytest.raises(CalibrationParseError, match="không phải camera đã khai"):
        parse_ros_transform_yaml(text, lidar_frame_id="velodyne", camera_frame_id="cam")
    assert (
        parse_ros_transform_yaml(text, lidar_frame_id="velodyne", camera_frame_id="imu_link").local_frame == "imu_link"
    )


@pytest.mark.parametrize("resolution", ["[null, null]", '["a", "b"]', "[0, 480]", "[752]"])
def test_kalibr_bad_resolution_is_a_parse_error_not_a_type_error(resolution: str) -> None:
    broken = KALIBR.replace("resolution: [752, 480]", f"resolution: {resolution}")
    with pytest.raises(CalibrationParseError, match="resolution"):
        parse_kalibr_camchain(broken)


def test_kalibr_imu_frame_name_follows_the_ros_file() -> None:
    (camera,) = parse_kalibr_camchain(KALIBR, imu_frame="imu_link")
    assert camera.camera_from_imu is not None and camera.camera_from_imu.local_frame == "imu_link"
    lidar_from_imu = Extrinsic("lidar", "imu_link", (0, 0, 0), (0, 0, 0, 1), "kalibr_camchain")
    assert compose_lidar_from_camera(camera.camera_from_imu, lidar_from_imu).parent_frame == "lidar"


def test_torwic_text_with_a_duplicate_key_is_refused() -> None:
    with pytest.raises(CalibrationParseError, match="trùng"):
        parse_torwic_text(_torwic_text() + "T_cam1_os.px: 1\n")


# ---------------------------------------------------------------------------
# Kalibr: camera ↔ IMU, không có LiDAR
# ---------------------------------------------------------------------------

# Ví dụ trong Kalibr wiki (yaml-formats): T_cam_imu là IMU → camera.
KALIBR = """\
# synthetic: ví dụ từ Kalibr wiki
cam0:
  camera_model: pinhole
  intrinsics: [461.629, 460.152, 362.680, 246.049]
  distortion_model: radtan
  distortion_coeffs: [-0.27695497, 0.06712482, 0.00087538, 0.00011556]
  T_cam_imu:
  - [0.01779318, 0.99967549, -0.01822936, 0.07008565]
  - [-0.9998017, 0.01795239, 0.00860714, -0.01771023]
  - [0.00893160, 0.01807260, 0.99979678, 0.00399246]
  - [0.0, 0.0, 0.0, 1.0]
  timeshift_cam_imu: -8.121e-05
  rostopic: /cam0/image_raw
  resolution: [752, 480]
"""


def test_kalibr_camchain_reads_intrinsics_and_the_imu_direction() -> None:
    (camera,) = parse_kalibr_camchain(KALIBR)
    assert camera.camera_model == "pinhole"
    assert camera.intrinsics == (461.629, 460.152, 362.680, 246.049)
    assert camera.distortion_model == "radtan"
    assert camera.resolution == (752, 480)
    assert camera.timeshift_cam_imu_seconds == pytest.approx(-8.121e-05)
    pose = camera.camera_from_imu
    assert pose is not None
    # T_cam_imu: điểm trong hệ IMU → hệ camera, nên cha là camera và con là IMU.
    assert pose.parent_frame == "cam0" and pose.local_frame == "imu"
    assert pose.translation_xyz == pytest.approx((0.07008565, -0.01771023, 0.00399246))


def test_kalibr_alone_gives_no_lidar_extrinsic() -> None:
    (camera,) = parse_kalibr_camchain(KALIBR)
    assert camera.camera_from_imu is not None and camera.camera_from_imu.parent_frame != "lidar"


def test_composing_with_an_imu_to_lidar_extrinsic_reproduces_the_chain() -> None:
    (camera,) = parse_kalibr_camchain(KALIBR)
    camera_from_imu = camera.camera_from_imu
    assert camera_from_imu is not None
    lidar_from_imu = Extrinsic(
        "lidar", "imu", (0.1, -0.2, 0.3), (0.0, 0.0, math.sin(0.4), math.cos(0.4)), "kalibr_camchain"
    )

    lidar_from_camera = compose_lidar_from_camera(camera_from_imu, lidar_from_imu)

    assert lidar_from_camera.parent_frame == "lidar" and lidar_from_camera.local_frame == "cam0"
    assert np.allclose(lidar_from_camera.matrix() @ camera_from_imu.matrix(), lidar_from_imu.matrix(), atol=1e-9)


def test_composition_refuses_extrinsics_that_do_not_share_the_imu_frame() -> None:
    (camera,) = parse_kalibr_camchain(KALIBR)
    assert camera.camera_from_imu is not None
    other = Extrinsic("lidar", "gyro", (0, 0, 0), (0, 0, 0, 1), "kalibr_camchain")
    with pytest.raises(CalibrationParseError, match="không chung frame IMU"):
        compose_lidar_from_camera(camera.camera_from_imu, other)


# ---------------------------------------------------------------------------
# Nhận diện định dạng và chuẩn hoá cho gói
# ---------------------------------------------------------------------------


def test_detect_format_recognizes_every_supported_calibration_by_content() -> None:
    assert detect_format(_torwic_text()) == "torwic_text"
    assert detect_format(_json_quaternion()) == "lidar_camera_json"
    assert detect_format(_json_inverse()) == "lidar_camera_json"  # chỉ có camera_from_lidar
    assert detect_format(_ros_yaml(parent="velodyne", child="cam")) == "ros_transform_yaml"
    assert detect_format(KALIBR) == "kalibr_camchain"


@pytest.mark.parametrize(
    "text",
    ["", "hello world", "key: value\n", '{"other": 1}', "{broken", "- a\n- b\n", "child_frame_id: only-this\n"],
)
def test_detect_format_returns_none_for_everything_else(text: str) -> None:
    assert detect_format(text) is None


def test_canonical_json_is_none_when_the_package_reader_already_understands_the_file() -> None:
    assert canonical_lidar_camera_json(_torwic_text(), lidar_frame_id=None) is None
    assert canonical_lidar_camera_json(_json_quaternion(), lidar_frame_id=None) is None


def test_canonical_json_normalizes_matrix_inverse_and_ros_to_the_same_transform() -> None:
    import json as _json

    for text, frame in (
        (_json_matrix(), None),
        (_json_inverse(), None),
        (_ros_yaml(parent="velodyne", child="cam"), "velodyne"),
        (_ros_yaml(parent="cam", child="velodyne", invert=True), "velodyne"),
    ):
        canonical = canonical_lidar_camera_json(text, lidar_frame_id=frame)
        assert canonical is not None
        block = _json.loads(canonical)["lidar_from_camera"]
        assert block["translation_xyz"] == pytest.approx(TRANSLATION, abs=1e-9)
        assert _rotation(tuple(block["rotation_xyzw"])) == pytest.approx(_rotation(QUATERNION), abs=1e-9)


def test_canonical_json_keeps_the_camera_intrinsics_block_of_a_json_source() -> None:
    import json as _json

    document = _json.loads(_json_matrix())
    document["camera"] = {"width": 1280, "height": 720, "fx": 600.0, "fy": 600.0, "cx": 640.0, "cy": 360.0}
    canonical = canonical_lidar_camera_json(_json.dumps(document), lidar_frame_id=None)
    assert canonical is not None and _json.loads(canonical)["camera"]["width"] == 1280


def test_canonical_json_refuses_a_file_that_is_not_a_camera_lidar_calibration() -> None:
    with pytest.raises(CalibrationParseError, match="không phải calibration camera"):
        canonical_lidar_camera_json(KALIBR, lidar_frame_id="velodyne")
    with pytest.raises(CalibrationParseError, match="chưa biết frame nào là LiDAR"):
        canonical_lidar_camera_json(_ros_yaml(parent="a", child="b"), lidar_frame_id=None)


# ---------------------------------------------------------------------------
# Số nguyên khổng lồ: lỗi dữ liệu của người dùng, không được thành OverflowError (500 ở route upload)
# ---------------------------------------------------------------------------

_HUGE = "1" + "0" * 400


@pytest.mark.parametrize(
    "text",
    [
        '{"camera_from_lidar": {"translation_xyz": [' + _HUGE + ', 0, 0], "rotation_xyzw": [0, 0, 0, 1]}}',
        '{"lidar_from_camera": {"matrix": [[1, 0, 0, ' + _HUGE + "], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]}}",
    ],
    ids=["translation", "matrix"],
)
def test_a_huge_integer_in_json_is_a_parse_error_not_an_overflow(text: str) -> None:
    with pytest.raises(CalibrationParseError):
        parse_lidar_camera_json(text)
    with pytest.raises(CalibrationParseError):
        canonical_lidar_camera_json(text, lidar_frame_id=None)


def test_a_huge_integer_in_ros_yaml_is_a_parse_error_not_an_overflow() -> None:
    text = (
        "header: {frame_id: os_sensor}\nchild_frame_id: camera\n"
        f"transform:\n  translation: {{x: {_HUGE}, y: 0, z: 0}}\n  rotation: {{x: 0, y: 0, z: 0, w: 1}}\n"
    )
    with pytest.raises(CalibrationParseError):
        parse_ros_transform_yaml(text, lidar_frame_id="os_sensor", camera_frame_id="camera")


def test_an_infinite_kalibr_resolution_is_a_parse_error_not_an_overflow() -> None:
    text = "cam0:\n  camera_model: pinhole\n  intrinsics: [1, 1, 1, 1]\n  resolution: [.inf, 480]\n"
    with pytest.raises(CalibrationParseError):
        parse_kalibr_camchain(text)
