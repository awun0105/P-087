"""REC-03 dựng bám theo quỹ đạo (ADR 0009): chuẩn bị ràng buộc cho COLMAP và nhánh riêng trong adapter.

COLMAP thật không chạy ở đây (fixture chỉ kiểm orchestration + database/file do team viết); lượt chạy thật trên
Aisle_CW ghi ở ADR 0009.
"""

import json
import math
import sqlite3
import struct
from pathlib import Path

import numpy as np
import pytest

from src.models.contracts.coordinates import Transform
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.adapters.colmap import ColmapAdapter, ColmapDependencies, ColmapRequest
from src.services.reconstruction.adapters.colmap_priors import (
    PoseGuidance,
    PosePrior,
    PosePriorError,
    guided_commands,
    prepare_guidance,
)
from src.services.reconstruction.adapters.colmap_runtime import ColmapError
from src.services.reconstruction.lidar.camera_priors import CameraPriorError, camera_priors
from src.services.reconstruction.lidar.fusion import ScanPose
from src.services.reconstruction.preview_models import PreparedPreviewRequest
from tests.test_reconstruction.test_rec03_colmap import FixtureProcess, config, frame_source, sparse

IDENTITY = (0.0, 0.0, 0.0, 1.0)
QUARTER_TURN = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))
SCHEMA = """
CREATE TABLE cameras (camera_id INTEGER PRIMARY KEY, model INTEGER, width INTEGER, height INTEGER, params BLOB,
                      prior_focal_length INTEGER);
CREATE TABLE images (image_id INTEGER PRIMARY KEY, name TEXT, camera_id INTEGER);
CREATE TABLE pose_priors (pose_prior_id INTEGER PRIMARY KEY, corr_data_id INTEGER, corr_sensor_id INTEGER,
                          corr_sensor_type INTEGER, position BLOB, position_covariance BLOB, gravity BLOB,
                          coordinate_system INTEGER);
"""


def _database(workspace: Path, names: tuple[str, ...], width: int = 640, height: int = 360) -> None:
    """Database tối thiểu theo schema COLMAP 4.x sau bước trích + ghép đặc trưng (camera SIMPLE_RADIAL đoán)."""
    workspace.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(workspace / "database.db")
    database.executescript(SCHEMA)
    guess = np.asarray([768.0, width / 2, height / 2, 0.0], dtype="<f8").tobytes()
    database.execute("INSERT INTO cameras VALUES (1, 2, ?, ?, ?, 0)", (width, height, guess))
    for index, name in enumerate(names):
        database.execute("INSERT INTO images VALUES (?, ?, 1)", (index + 1, name))
    database.commit()
    database.close()


def _guidance(names: tuple[str, ...], calibrated: bool = True) -> PoseGuidance:
    priors = tuple(PosePrior(name, (float(index), 0.0, 1.5), IDENTITY) for index, name in enumerate(names))
    calibration = (1280, 720, (620.0, 620.0, 650.0, 368.0, 0.07, -0.03, 0.001, 0.002)) if calibrated else None
    return PoseGuidance(priors, calibration)


def test_sensor_pose_and_calibration_give_the_camera_pose() -> None:
    """Cảm biến ở (4, 0, 1) quay 90° quanh Z, camera lệch 0,1 m theo trục x của cảm biến → camera ở (4, 0,1, 1)."""
    poses = [ScanPose(0.0, (0.0, 0.0, 1.0), IDENTITY), ScanPose(0.1, (4.0, 0.0, 1.0), QUARTER_TURN)]
    offset = Transform(
        parent_frame="lidar_sensor",
        local_frame="camera",
        translation_xyz=(0.1, 0.0, 0.0),
        rotation_quaternion_xyzw=IDENTITY,
    )
    first, second = camera_priors(poses, offset, (0, 1))
    assert first.translation == pytest.approx((0.1, 0.0, 1.0))
    assert second.translation == pytest.approx((4.0, 0.1, 1.0))
    assert second.rotation_xyzw == pytest.approx(QUARTER_TURN)
    with pytest.raises(CameraPriorError, match="quỹ đạo chỉ có 2 pose"):
        camera_priors(poses, offset, (0, 5))


def test_prior_model_and_position_priors_are_written_for_colmap(tmp_path: Path) -> None:
    names = ("000000.png", "000004.png")
    _database(tmp_path, names)
    prepare_guidance(tmp_path, _guidance(names))
    database = sqlite3.connect(tmp_path / "database.db")
    rows = database.execute(
        "SELECT corr_data_id, corr_sensor_id, corr_sensor_type, position, coordinate_system FROM pose_priors ORDER BY 1"
    ).fetchall()
    assert [(row[0], row[1], row[2], struct.unpack("<3d", row[3]), row[4]) for row in rows] == [
        (1, 1, 0, (0.0, 0.0, 1.5), 1),
        (2, 1, 0, (1.0, 0.0, 1.5), 1),
    ]
    model, blob = database.execute("SELECT model, params FROM cameras").fetchone()
    # Calibration ở 1280×720, ảnh trích ở 640×360: tiêu cự và tâm ảnh giảm một nửa, hệ số méo giữ nguyên.
    assert model == 4
    assert list(np.frombuffer(blob, dtype="<f8")) == pytest.approx([310, 310, 325, 184, 0.07, -0.03, 0.001, 0.002])
    cameras = (tmp_path / "prior_model/cameras.txt").read_text().split()
    assert cameras[:4] == ["1", "OPENCV", "640", "360"]
    lines = [line.split() for line in (tmp_path / "prior_model/images.txt").read_text().splitlines() if line]
    # COLMAP lưu camera_from_world: pose đơn vị tại (1, 0, 1,5) → tịnh tiến (−1, 0, −1,5).
    assert [float(value) for value in lines[1][1:8]] == pytest.approx([1, 0, 0, 0, -1, 0, -1.5])
    assert lines[1][8:] == ["1", "000004.png"]
    assert (tmp_path / "prior_model/points3D.txt").read_text() == "" and (tmp_path / "prior_sparse").is_dir()


def test_guidance_keeps_colmap_intrinsics_when_package_has_none(tmp_path: Path) -> None:
    names = ("000000.png", "000001.png")
    _database(tmp_path, names)
    prepare_guidance(tmp_path, _guidance(names, calibrated=False))
    assert (tmp_path / "prior_model/cameras.txt").read_text().split()[:2] == ["1", "SIMPLE_RADIAL"]
    refine = guided_commands(config(), _guidance(names, calibrated=False))[1]
    assert "--Mapper.ba_refine_focal_length" not in refine  # không có calibration thì để COLMAP tinh chỉnh tiêu cự


def test_guided_commands_replace_the_mapper() -> None:
    triangulate, refine = guided_commands(config(num_threads=3), _guidance(("a.png", "b.png")))
    assert triangulate[0] == "point_triangulator" and "--clear_points" in triangulate
    assert refine[0] == "pose_prior_mapper"
    assert refine[refine.index("--input_path") + 1] == "prior_sparse"
    assert refine[refine.index("--output_path") + 1] == "sparse/0"
    assert refine[refine.index("--prior_position_std_x") + 1] == "0.05"
    assert refine[refine.index("--Mapper.ba_refine_focal_length") + 1] == "0"


def test_guidance_rejects_mismatched_images_cropped_video_and_old_colmap(tmp_path: Path) -> None:
    _database(tmp_path / "names", ("000000.png", "000001.png"))
    with pytest.raises(PosePriorError, match="khác danh sách pose"):
        prepare_guidance(tmp_path / "names", _guidance(("000000.png", "000009.png")))
    _database(tmp_path / "crop", ("000000.png", "000001.png"), width=640, height=640)
    with pytest.raises(PosePriorError, match="khác tỉ lệ khung hình"):
        prepare_guidance(tmp_path / "crop", _guidance(("000000.png", "000001.png")))
    (tmp_path / "old").mkdir()
    old = sqlite3.connect(tmp_path / "old/database.db")
    old.execute("CREATE TABLE pose_priors (image_id INTEGER, position BLOB)")
    old.close()
    with pytest.raises(PosePriorError, match="COLMAP ≥ 4.0"):
        prepare_guidance(tmp_path / "old", _guidance(("000000.png",)))


class GuidedProcess(FixtureProcess):
    """COLMAP giả cho nhánh bám quỹ đạo: bước ghép đặc trưng để lại database, model cuối nằm ở `sparse/0`."""

    def run(self, arguments: list[str], workspace: Path) -> str:
        self.commands.append(arguments)
        if arguments[0] == "sequential_matcher":
            _database(workspace, tuple(sorted(path.name for path in (workspace / "images").iterdir())))
        if arguments[0] == "model_converter":
            sparse(workspace / arguments[arguments.index("--output_path") + 1], (0, 1, 2, 3))
        return ""


def _adapter(
    root: Path, guidance: PoseGuidance | None
) -> tuple[ColmapAdapter, ColmapRequest, GuidedProcess, ArtifactResolver]:
    frames, reference = frame_source(root / "source")
    resolver = ArtifactResolver(root / "store")
    process = GuidedProcess()
    deps = ColmapDependencies(frames, process, FilesystemArtifactStore(resolver), resolver.require)
    return (
        ColmapAdapter(deps),
        ColmapRequest(reference, config(), root / "work", "rec03-guided", None, guidance),
        process,
        resolver,
    )


def test_adapter_runs_the_guided_path_and_records_offsets(tmp_path: Path) -> None:
    names = tuple(f"{index:06d}.png" for index in range(4))
    # Fixture ghi camera_from_world tịnh tiến (i, 0, 0) nên tâm camera i ở (−i, 0, 0); quỹ đạo đặt cao hơn 0,3 m.
    guidance = PoseGuidance(
        tuple(PosePrior(name, (-float(i), 0.0, 0.3), IDENTITY) for i, name in enumerate(names)), None
    )
    service, request, process, resolver = _adapter(tmp_path, guidance)
    result = service.execute(request)
    assert [command[0] for command in process.commands] == [
        "feature_extractor",
        "sequential_matcher",
        "point_triangulator",
        "pose_prior_mapper",
        "model_converter",
    ]
    assert len(result.artifact.poses) == 4
    assert result.guidance_ref is not None
    record = json.loads(resolver.require(result.guidance_ref).read_text())
    assert record["method"] == "trajectory_guided_colmap" and record["registered_frames"] == 4
    assert record["offset_median_m"] == pytest.approx(0.3) and record["offset_max_m"] == pytest.approx(0.3)
    assert record["camera_poses_checksum"] == result.reference.artifact_checksum


def test_adapter_without_guidance_still_uses_the_mapper(tmp_path: Path) -> None:
    frames, reference = frame_source(tmp_path / "source")
    resolver = ArtifactResolver(tmp_path / "store")
    process = FixtureProcess()
    deps = ColmapDependencies(frames, process, FilesystemArtifactStore(resolver), resolver.require)
    result = ColmapAdapter(deps).execute(ColmapRequest(reference, config(), tmp_path / "work", "rec03-plain"))
    assert [command[0] for command in process.commands][:3] == ["feature_extractor", "sequential_matcher", "mapper"]
    assert result.guidance_ref is None


def test_adapter_reports_unusable_guidance_as_a_user_fixable_error(tmp_path: Path) -> None:
    guidance = PoseGuidance((PosePrior("khac.png", (0.0, 0.0, 0.0), IDENTITY),), None)
    service, request, _, _ = _adapter(tmp_path, guidance)
    with pytest.raises(ColmapError) as error:
        service.execute(request)
    assert error.value.code == "COLMAP_GUIDANCE_INVALID" and "khác danh sách pose" in str(error.value)


def test_preview_request_without_lidar_keeps_its_bytes() -> None:
    """Trường mới không được xuất hiện trong JSON của job chỉ có video (artifact request cũ vẫn khớp checksum)."""
    field = PreparedPreviewRequest.model_fields["lidar_package_ref"]
    assert field.default is None and field.exclude_if is not None and field.exclude_if(None) is True
