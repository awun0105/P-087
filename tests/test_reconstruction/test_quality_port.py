"""Cổng chỉ số tự kiểm của EX-REC: đọc đúng field của artifact, không bịa số khi artifact không mang."""

import hashlib
import json
import math
import struct
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.services.reconstruction import quality
from src.services.reconstruction.finalize import load_geometry_profile
from src.services.reconstruction.metric_port import check_tolerance_m

_PROFILE = Path(__file__).resolve().parents[2] / "configs" / "product" / "geometry_v1.json"


class _Store:
    """Kho artifact tối thiểu: publish bytes dưới một URI và resolve ref về file (như `ArtifactResolver.require`)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, name: str, payload: bytes | dict, artifact_type: str = "Test") -> ProductArtifactRef:
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return ProductArtifactRef(
            artifact_type=artifact_type,
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/job-q/{name}",
            artifact_checksum="sha256:" + hashlib.sha256(data).hexdigest(),
            data_class="derived",
            producer_stage="ST-CAMERA-POSE",
            job_id="job-q",
        )

    def resolve(self, reference: ProductArtifactRef) -> Path:
        return self.root / reference.artifact_uri.removeprefix("artifact://jobs/job-q/")


@pytest.fixture
def store(tmp_path: Path) -> _Store:
    return _Store(tmp_path)


def test_input_quality_counts_accepted_frames_and_keeps_warnings(store: _Store) -> None:
    report = store.put(
        "quality.json",
        {
            "frames": [
                {"frame_id": 0, "blur_score": 4.0, "quality": "accepted"},
                {"frame_id": 1, "blur_score": 6.0, "quality": "accepted"},
                {"frame_id": 2, "blur_score": 1.0, "quality": "rejected"},
            ],
            "excluded_frame_ids": [2],
            "motion": {"active_ratio": 0.5, "motion_p90_px": 7.0, "warnings": ["static_run"]},
        },
    )
    result = quality.input_quality(report, store.resolve)
    assert (result.inspected_frames, result.accepted_frames, result.excluded_frames) == (3, 2, 1)
    assert result.blur_score_median == 4.0 and result.motion_active_ratio == 0.5
    assert result.warnings == ["static_run"]


def _poses(store: _Store, *, with_points: bool) -> ProductArtifactRef:
    document: dict = {
        "input_frame_ids": [0, 1, 2, 3],
        "registered_ratio": 0.75,
        "selected_model_id": "1",
        "models": [{"model_id": "0", "sparse_points": 5}, {"model_id": "1", "sparse_points": 2}],
        "config": {"min_registered_ratio": 0.5},
        "poses": [{"frame_id": index, "translation": [0, 0, 0]} for index in range(3)],
    }
    if with_points:
        points = "# header\n1 0 0 0 1 1 1 0.5 1 10 2 11\n2 0 0 0 1 1 1 1.5 1 12 2 13 3 14 4 15\n"
        document["sparse_files"] = {"points3D.txt": store.put("sparse/points3D.txt", points.encode()).model_dump()}
    return store.put("camera_poses.json", document)


def test_pose_quality_reads_registration_and_sparse_statistics(store: _Store) -> None:
    result = quality.pose_quality(_poses(store, with_points=True), store.resolve)
    assert (result.input_frames, result.registered_frames, result.registered_ratio) == (4, 3, 0.75)
    assert result.min_registered_ratio == 0.5 and result.sparse_points == 2
    assert result.mean_reprojection_error_px == pytest.approx(1.0)
    assert result.mean_track_length == pytest.approx(3.0)  # điểm 1 có 2 quan sát, điểm 2 có 4


def test_pose_quality_without_sparse_file_reports_unknown_not_zero(store: _Store) -> None:
    result = quality.pose_quality(_poses(store, with_points=False), store.resolve)
    assert result.mean_reprojection_error_px is None and result.mean_track_length is None


def test_visual_quality_reads_inspection_and_training_config(store: _Store) -> None:
    visual = store.put(
        "visual.json",
        {
            "inspection": {"num_gaussians": 1234, "nonfinite_count": 2},
            "training_frame_ids": [0, 1, 2],
            "config": {"total_train_iters": 7000},
        },
    )
    result = quality.visual_quality(visual, store.resolve)
    assert (result.gaussians, result.nonfinite_values, result.training_frames, result.train_iterations) == (
        1234,
        2,
        3,
        7000,
    )


def _confirmation(store: _Store, declared: dict) -> ProductArtifactRef:
    declaration = store.put("declaration.json", {"input": declared})
    return store.put(
        "confirmation.json",
        {
            "preview": {
                "transform": {"scale_m_per_sfm_unit": 2.0},
                "request": {"anchor": {"distance_m": 4.0, "measurement_ref": declaration.model_dump()}},
            }
        },
    )


def test_metric_quality_measures_the_independent_check_segment(store: _Store) -> None:
    declared = {"check_a": [0, 0, 0], "check_b": [1, 0, 0], "check_distance_m": 2.1, "distance_source": "user_measured"}
    result = quality.metric_quality(_confirmation(store, declared), store.resolve)
    assert result.scale_m_per_sfm_unit == 2.0 and result.anchor_distance_m == 4.0
    assert result.check_error_m == pytest.approx(0.1)  # 2.0 × 1 đơn vị SfM = 2.0 m, người dùng đo 2.1 m
    assert result.check_tolerance_m == pytest.approx(check_tolerance_m(4.0, 2.1))
    assert result.distance_source == "user_measured"


def test_metric_quality_without_check_segment_reports_unknown(store: _Store) -> None:
    result = quality.metric_quality(_confirmation(store, {"distance_source": "user_measured"}), store.resolve)
    assert result.check_error_m is None and result.check_tolerance_m is None


def _collision(store: _Store) -> ProductArtifactRef:
    """Collision GLB đúng layout của splat-transform: một khối tứ diện thấp quanh (3, 3), trong tầm cao robot."""
    points = ((3.0, 3.0, 0.1), (3.2, 3.0, 0.1), (3.0, 3.2, 0.1), (3.0, 3.0, 0.2))
    indices = (0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3)
    binary = b"".join(struct.pack("<fff", *point) for point in points) + struct.pack("<12I", *indices)
    document = {
        "asset": {"version": "2.0", "generator": "splat-transform"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 48, "target": 34962},
            {"buffer": 0, "byteOffset": 48, "byteLength": 48, "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 4,
                "type": "VEC3",
                "min": [min(point[axis] for point in points) for axis in range(3)],
                "max": [max(point[axis] for point in points) for axis in range(3)],
            },
            {"bufferView": 1, "componentType": 5125, "count": 12, "type": "SCALAR"},
        ],
    }
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    payload = struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
    payload += struct.pack("<I4s", len(encoded), b"JSON") + encoded
    payload += struct.pack("<I4s", len(binary), b"BIN\0") + binary
    return store.put("collision.glb", payload)


def _profile_checksum(gpu_index: int, **changes: float) -> str:
    profile = load_geometry_profile(_PROFILE).model_copy(update={"gpu_index": gpu_index, **changes})
    return "sha256:" + hashlib.sha256(profile.model_dump_json().encode()).hexdigest()


def test_geometry_quality_flags_only_camera_positions_the_mesh_occupies(store: _Store) -> None:
    radius = load_geometry_profile(_PROFILE).capsule_radius_m
    near = 3.0 - radius / 2  # cách khối chưa tới một bán kính robot
    poses = store.put(
        "metric_poses.json",
        {"poses": [{"translation": [0.0, 0.0, 1.0]}, {"translation": [near, 3.0, 1.0]}, {"translation": [-3, -3, 1]}]},
    )
    # Job chạy trên máy có GPU index khác: thông số hình học vẫn phải được nhận là cùng bản.
    result = quality.geometry_quality(_collision(store), poses, (_PROFILE, _profile_checksum(3)), store.resolve)
    assert (result.camera_positions, result.blocked_positions) == (3, 1)
    assert result.robot_radius_m == radius and result.triangles == 4
    assert math.isclose(result.voxel_resolution_m, load_geometry_profile(_PROFILE).resolution_m)


def test_geometry_quality_refuses_a_profile_that_differs_from_the_job(store: _Store) -> None:
    poses = store.put("metric_poses.json", {"poses": [{"translation": [0.0, 0.0, 1.0]}]})
    other = _profile_checksum(0, capsule_radius_m=9.0)
    with pytest.raises(quality.GeometryProfileMismatchError, match="khác bản đã dùng"):
        quality.geometry_quality(_collision(store), poses, (_PROFILE, other), store.resolve)
