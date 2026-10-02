"""Nhận gói LiDAR của người dùng (ADR 0009): giải gói, ghép scan nếu cần, publish đám mây đã đăng ký.

Gói là ZIP đã qua nhận diện (`inputs/detect.py`): quỹ đạo TUM, calibration camera ↔ LiDAR, thời điểm frame, cộng với
hoặc các scan `.pcd` chưa đăng ký (ghép theo quỹ đạo ở đây), hoặc một đám mây đã đăng ký. Kết quả:

- `LiDARGeometryArtifact` (REC-08) trong hệ `lidar_map` của quỹ đạo, kèm phép dịch sàn về z = 0 của `world`;
- `LidarPackageRecord`: quỹ đạo, thời điểm frame, calibration và số liệu ghép — đầu vào của bước dựng pose camera.

Module không căn chỉnh với RGB và không ước lượng quỹ đạo. Nguồn gốc quỹ đạo do người dùng khai (tự tính hay ground
truth) đi thẳng vào provenance: contract bắt buộc ghi `ground_truth_assisted` khi dùng quỹ đạo ground truth.
"""

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import numpy as np
from pydantic import Field, FiniteFloat

from src.models.contracts.artifacts import ArtifactDataClass, Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem, Transform
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import DependencyOrigin, PreprocessingDependency, PreprocessingProvenance
from src.services.reconstruction.adapters.torwic_calibration import normalize_torwic_extrinsics
from src.services.reconstruction.inputs.detect import LidarEvidence
from src.services.reconstruction.lidar.fusion import (
    FusionConfig,
    FusionStats,
    ScanPose,
    fuse_scans,
    parse_trajectory,
    ply_bytes,
    read_points,
)
from src.services.reconstruction.lidar.ingest import LiDARIngestService
from src.services.reconstruction.lidar.models import LiDARIngestRequest
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter

#: Hệ toạ độ của quỹ đạo người dùng nộp (cố định, mét, Z hướng lên); `world` = hệ này dịch sàn về z = 0.
MAP_FRAME = "lidar_map"
SENSOR_FRAME = "lidar_sensor"
CAMERA_FRAME = "camera"
TrajectoryOrigin = Literal["estimated", "ground_truth"]

_FLOOR_RADIUS_M = 3.0
_FLOOR_BIN_M = 0.02
_FLOOR_MIN_POINTS = 500
#: Điểm sàn phải thấp hơn cảm biến ít nhất chừng này (loại chính thân robot và vật ngang tầm cảm biến).
_FLOOR_BELOW_SENSOR_M = 0.3


class LidarPackageError(ValueError):
    """Gói LiDAR không xử lý được; message hiển thị được cho người dùng."""


class LidarPackageRecord(ContractModel):
    """Bản ghi của gói LiDAR sau khi nhận: mọi thứ bước dựng pose camera và căn chỉnh cần, theo checksum."""

    schema_version: Literal["1.0"] = "1.0"
    artifact_type: Literal["LidarPackageRecord"] = "LidarPackageRecord"
    job_id: str
    kind: Literal["registered_lidar", "lidar_scan_sequence"]
    trajectory_origin: TrajectoryOrigin
    pose_count: int = Field(gt=1)
    trajectory_ref: ProductArtifactRef
    frame_times_ref: ProductArtifactRef
    #: `lidar_sensor_from_camera`: vị trí và hướng camera trong hệ cảm biến LiDAR.
    sensor_from_camera: Transform
    lidar_geometry_ref: ProductArtifactRef
    lidar_metadata_ref: ProductArtifactRef
    point_count: int = Field(gt=0)
    #: Cao độ mặt sàn ước lượng trong hệ quỹ đạo (mét) và số điểm làm căn cứ.
    floor_z_m: FiniteFloat
    floor_support_points: int = Field(ge=_FLOOR_MIN_POINTS)
    fusion: FusionStats | None = None
    record_checksum: Checksum


@dataclass(frozen=True)
class LidarPackageResult:
    """Bản ghi đã publish và ref của nó (đi vào stage `ST-LIDAR-INGEST` của JobManifest)."""

    record: LidarPackageRecord
    reference: ProductArtifactRef


def _sha256(payload: bytes) -> Checksum:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def parse_calibration(text: str, fmt: Literal["torwic_txt", "json"]) -> Transform:
    """`lidar_sensor_from_camera` từ calibration của gói; quaternion phải gần đơn vị (không tự sửa dữ liệu sai)."""
    try:
        if fmt == "json":
            block = json.loads(text)["lidar_from_camera"]
            translation, rotation = tuple(block["translation_xyz"]), tuple(block["rotation_xyzw"])
        else:
            values: dict[str, float] = {}
            for line in text.splitlines():
                key, _, raw = line.split("#", 1)[0].partition(":")
                if key.strip().startswith("T_cam1_os."):
                    values[key.strip().removeprefix("T_cam1_os.")] = float(raw)
            translation = (values["px"], values["py"], values["pz"])
            rotation = (values["qx"], values["qy"], values["qz"], values["qw"])
        if len(translation) != 3 or len(rotation) != 4:
            raise ValueError("sai số phần tử")
        return normalize_torwic_extrinsics(
            tuple(float(value) for value in translation),  # type: ignore[arg-type]
            tuple(float(value) for value in rotation),  # type: ignore[arg-type]
            (SENSOR_FRAME, CAMERA_FRAME),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise LidarPackageError(f"Calibration camera ↔ LiDAR không đọc được: {error}") from error


def parse_frame_times(text: str, pose_count: int) -> list[float]:
    """Thời điểm frame: một số mỗi dòng, tăng dần, đúng một dòng cho mỗi pose."""
    try:
        times = [float(line) for line in text.splitlines() if line.strip() and not line.startswith("#")]
    except ValueError as error:
        raise LidarPackageError("File thời điểm frame có dòng không phải số") from error
    if len(times) != pose_count or any(later <= earlier for earlier, later in zip(times, times[1:], strict=False)):
        raise LidarPackageError(f"File thời điểm frame cần {pose_count} dòng tăng dần, khớp với quỹ đạo")
    return times


def estimate_floor(points: np.ndarray, poses: list[ScanPose]) -> tuple[float, int]:
    """Cao độ sàn trong hệ quỹ đạo: mức z có nhiều điểm nhất ở ngay dưới đường đi của cảm biến.

    Giả định hệ của quỹ đạo có Z hướng lên (ADR 0009). Không đủ điểm dưới quỹ đạo thì báo lỗi thay vì đoán — thường
    là do trục lên không phải Z hoặc quỹ đạo không thuộc đám mây này.
    """
    track = np.array([pose.translation for pose in poses])
    step = max(1, len(track) // 200)
    near = np.zeros(len(points), dtype=bool)
    for position in track[::step]:
        near |= np.linalg.norm(points[:, :2] - position[:2], axis=1) < _FLOOR_RADIUS_M
    below = points[near & (points[:, 2] < track[:, 2].min() - _FLOOR_BELOW_SENSOR_M)]
    if len(below) < _FLOOR_MIN_POINTS:
        raise LidarPackageError(
            "Không tìm thấy mặt sàn dưới quỹ đạo trong đám mây LiDAR. Kiểm tra quỹ đạo có thuộc đúng đám mây này "
            "không, và hệ toạ độ có trục Z hướng lên, đơn vị mét không."
        )
    bins = np.floor(below[:, 2] / _FLOOR_BIN_M).astype(np.int64)
    values, counts = np.unique(bins, return_counts=True)
    best = int(values[counts.argmax()])
    support = below[(bins >= best - 1) & (bins <= best + 1)]
    return float(np.median(support[:, 2])), int(len(support))


class LidarPackageIngest:
    """Một lần nhận gói cho một job; không giữ state ngoài artifact đã publish."""

    def __init__(self, writer: ArtifactWriter, config: FusionConfig | None = None) -> None:
        self.writer = writer
        self.config = config or FusionConfig()

    def ingest(
        self,
        package: Path,
        evidence: LidarEvidence,
        job_id: str,
        trajectory_origin: TrajectoryOrigin,
        workspace: Path,
    ) -> LidarPackageResult:
        """Giải gói theo bằng chứng nhận diện, ghép nếu là scan thô, publish đám mây + bản ghi gói."""
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(package) as archive:
                trajectory_bytes = archive.read(evidence.trajectory_member)
                times_bytes = archive.read(evidence.frame_times_member)
                calibration_bytes = archive.read(evidence.calibration_member)
                poses = self._poses(trajectory_bytes, evidence)
                parse_frame_times(times_bytes.decode("utf-8"), len(poses))
                sensor_from_camera = parse_calibration(calibration_bytes.decode("utf-8"), evidence.calibration_format)
                points, payload, fmt, fusion, scan_checksums = self._cloud(archive, evidence, poses)
        except (KeyError, zipfile.BadZipFile, UnicodeDecodeError) as error:
            raise LidarPackageError("Gói LiDAR hỏng hoặc đã đổi sau khi tải lên") from error
        floor_z, support = estimate_floor(points, poses)
        cloud_path = workspace / f"registered_lidar.{fmt}"
        cloud_path.write_bytes(payload)
        origin = DependencyOrigin.GROUND_TRUTH if trajectory_origin == "ground_truth" else DependencyOrigin.ESTIMATED
        dependencies = [
            PreprocessingDependency(role="pose", origin=origin, source_checksum=_sha256(trajectory_bytes)),
            PreprocessingDependency(
                role="calibration", origin=DependencyOrigin.SENSOR_INPUT, source_checksum=_sha256(calibration_bytes)
            ),
            PreprocessingDependency(
                role="timestamps", origin=DependencyOrigin.SENSOR_INPUT, source_checksum=_sha256(times_bytes)
            ),
            *(
                PreprocessingDependency(role="scan", origin=DependencyOrigin.SENSOR_INPUT, source_checksum=checksum)
                for checksum in scan_checksums
            ),
        ]
        provenance = PreprocessingProvenance(
            dependencies=dependencies,
            ground_truth_assisted=trajectory_origin == "ground_truth",
            details={
                "source": "user_lidar_package",
                "package_kind": "lidar_scan_sequence" if fusion is not None else "registered_lidar",
                "floor_z_in_source_m": floor_z,
                "floor_source": "estimated_from_cloud_below_trajectory",
                "up_axis_source": "declared_by_package_convention",
                **(
                    {"fusion": {**self.config.model_dump(mode="json"), **fusion.model_dump(mode="json")}}
                    if fusion
                    else {}
                ),
            },
        )
        lidar = LiDARIngestService(self.writer).ingest_with_metadata(
            LiDARIngestRequest(
                job_id=job_id,
                lidar_file=cloud_path,
                source_input_checksum=_sha256(payload),
                geometry_format=fmt,
                coordinate_system=CoordinateSystem(),
                source_frame=MAP_FRAME,
                declared_transform_to_canonical=Transform(
                    parent_frame="world",
                    local_frame=MAP_FRAME,
                    translation_xyz=(0.0, 0.0, -floor_z),
                    rotation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
                ),
                preprocessing_provenance=provenance,
            )
        )
        base = PurePosixPath(lidar.metadata_ref.artifact_uri.removeprefix("artifact://")).parent
        record = LidarPackageRecord(
            job_id=job_id,
            kind="lidar_scan_sequence" if fusion is not None else "registered_lidar",
            trajectory_origin=trajectory_origin,
            pose_count=len(poses),
            trajectory_ref=self._publish(
                job_id, f"{base}/trajectory.txt", trajectory_bytes, "LidarTrajectory", provenance
            ),
            frame_times_ref=self._publish(
                job_id, f"{base}/frame_times.txt", times_bytes, "LidarFrameTimes", provenance
            ),
            sensor_from_camera=sensor_from_camera,
            lidar_geometry_ref=lidar.geometry_ref,
            lidar_metadata_ref=lidar.metadata_ref,
            point_count=len(points),
            floor_z_m=floor_z,
            floor_support_points=support,
            fusion=fusion,
            record_checksum="sha256:" + "0" * 64,
        )
        record = record.model_copy(update={"record_checksum": canonical_content_checksum(record, "record_checksum")})
        body = record.model_dump_json(indent=2).encode("utf-8") + b"\n"
        reference = self._publish(job_id, f"{base}/lidar_package.json", body, "LidarPackageRecord", provenance)
        return LidarPackageResult(record, reference)

    def _poses(self, trajectory_bytes: bytes, evidence: LidarEvidence) -> list[ScanPose]:
        try:
            poses = parse_trajectory(trajectory_bytes.decode("utf-8"))
        except ValueError as error:
            raise LidarPackageError(f"Quỹ đạo không hợp lệ: {error}") from error
        if len(poses) != evidence.pose_count:
            raise LidarPackageError("Quỹ đạo đã đổi so với lúc tải lên")
        return poses

    def _cloud(
        self, archive: zipfile.ZipFile, evidence: LidarEvidence, poses: list[ScanPose]
    ) -> tuple[np.ndarray, bytes, Literal["ply", "pcd"], FusionStats | None, list[Checksum]]:
        """Đám mây trong hệ quỹ đạo: bytes gốc của file đã đăng ký, hoặc PLY ghép từ scan thô."""
        try:
            if evidence.cloud_member is not None:
                payload = archive.read(evidence.cloud_member)
                points = read_points(io.BytesIO(payload), self.config.max_merged_points)
                return points, payload, evidence.geometry_format, None, []
            names = sorted(name for name in archive.namelist() if PurePosixPath(name).suffix.lower() == ".pcd")
            if len(names) != evidence.scan_count:
                raise LidarPackageError("Số scan trong gói đã đổi so với lúc tải lên")
            checksums: list[Checksum] = []
            points, stats = fuse_scans(self._scans(archive, names, evidence, poses, checksums), self.config)
            return points, ply_bytes(points), "ply", stats, checksums
        except LidarPackageError:
            raise
        except ValueError as error:
            raise LidarPackageError(f"Không ghép được đám mây LiDAR: {error}") from error

    def _scans(
        self,
        archive: zipfile.ZipFile,
        names: list[str],
        evidence: LidarEvidence,
        poses: list[ScanPose],
        checksums: list[Checksum],
    ) -> Iterator[tuple[np.ndarray, ScanPose]]:
        """Từng scan cùng pose của nó; ghi checksum bytes gốc vào `checksums` để truy vết."""
        for index, name in enumerate(names):
            payload = archive.read(name)
            checksums.append(_sha256(payload))
            pose_index = int(PurePosixPath(name).stem) if evidence.pairing == "index_in_name" else index
            try:
                yield read_points(io.BytesIO(payload), self.config.max_scan_points), poses[pose_index]
            except ValueError as error:
                raise LidarPackageError(f"Scan {PurePosixPath(name).name} không đọc được: {error}") from error

    def _publish(
        self, job_id: str, relative: str, payload: bytes, artifact_type: str, provenance: PreprocessingProvenance
    ) -> ProductArtifactRef:
        reference = ProductArtifactRef(
            artifact_type=artifact_type,
            schema_version="1.0",
            artifact_uri=f"artifact://{relative}",
            artifact_checksum=_sha256(payload),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.LIDAR_INGEST,
            job_id=job_id,
            source_provenance={"ground_truth_assisted": provenance.ground_truth_assisted},
        )
        if self.writer.publish(reference, payload) != reference:
            raise ValueError("artifact store changed LiDAR package publication identity")
        return reference
