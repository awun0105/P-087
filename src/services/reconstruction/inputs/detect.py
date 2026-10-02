"""Nhận diện loại đầu vào theo nội dung file (ADR 0004 §1, ADR 0009 §1), không tin đuôi file.

Chỉ đọc header/danh mục; không giải nén hay parse toàn bộ payload. Kết quả là
bằng chứng để PRODUCT lưu cùng upload và worker chọn luồng. File không khớp loại
nào bị từ chối với lý do hiển thị được cho người dùng, không đoán.
"""

import math
import struct
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.services.reconstruction.lidar.cloud_header import read_header

InputKind = Literal["rgb_video", "gaussian_ply", "gaussian_ply_colmap", "registered_lidar", "lidar_scan_sequence"]

#: Thuộc tính bắt buộc của một Gaussian (vị trí, màu SH bậc 0, opacity, scale, rotation).
GAUSSIAN_FIELDS = ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2") + tuple(
    f"rot_{index}" for index in range(4)
)
#: Số hệ số f_rest theo bậc SH 0..3 (3 kênh màu × (bậc+1)² − 1).
_SH_REST = {0: 0, 9: 1, 24: 2, 45: 3}
_QUICKTIME_ATOMS = {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip"}
_COLMAP_FILES = ("cameras", "images", "points3D")
_MAX_ZIP_ENTRIES = 20000
#: File quỹ đạo là văn bản nhỏ (một dòng mỗi pose); lớn hơn mức này không phải quỹ đạo.
_MAX_TRAJECTORY_BYTES = 16 * 1024 * 1024
_TRAJECTORY_SUFFIXES = {".txt", ".tum", ".csv"}
_QUATERNION_TOLERANCE = 1e-3
NO_TRAJECTORY = (
    "Tìm thấy {scans} scan LiDAR (.pcd) nhưng không có file quỹ đạo. Hệ thống không tự ước lượng quỹ đạo "
    "(LiDAR odometry/SLAM chưa hỗ trợ). Thêm vào ZIP một file quỹ đạo dạng TUM — mỗi dòng "
    "`thời_điểm x y z qx qy qz qw`, một dòng cho mỗi scan — hoặc tải lên đám mây LiDAR đã đăng ký (.ply/.pcd)."
)


class InputRejectedError(ValueError):
    """File không thuộc loại được hỗ trợ; message hiển thị được cho người dùng."""


class GaussianPlyEvidence(BaseModel):
    """Header 3DGS đã kiểm: số Gaussian, bậc SH, encoding."""

    model_config = ConfigDict(extra="forbid")

    gaussian_count: int = Field(gt=0)
    sh_degree: int = Field(ge=0, le=3)
    encoding: str


class LidarEvidence(BaseModel):
    """Bằng chứng LiDAR đã kiểm ở header (ADR 0009 §1).

    Đám mây đã đăng ký: `point_count`. Chuỗi scan: `scan_count`, `pose_count`, file quỹ đạo và cách ghép scan ↔ pose.
    Đây là kiểm tra ở mức danh mục; bước `ST-LIDAR-INGEST` mới đọc toàn bộ điểm.
    """

    model_config = ConfigDict(extra="forbid")

    geometry_format: Literal["ply", "pcd"]
    point_count: int | None = Field(default=None, gt=0)
    scan_count: int | None = Field(default=None, gt=1)
    pose_count: int | None = Field(default=None, gt=1)
    trajectory_member: str | None = None
    #: `index_in_name`: tên scan là chỉ số dòng trong quỹ đạo (vd. 000421.pcd ↔ pose 421, cho phép nộp một phần scan);
    #: `sorted_order`: scan thứ i theo thứ tự tên ↔ pose thứ i (số lượng phải bằng nhau).
    pairing: Literal["index_in_name", "sorted_order"] | None = None


class InputDetection(BaseModel):
    """Loại đầu vào + bằng chứng; `ply_member`/`colmap_dir` chỉ có với ZIP 3DGS, `lidar` chỉ có với LiDAR."""

    model_config = ConfigDict(extra="forbid")

    kind: InputKind
    gaussian: GaussianPlyEvidence | None = None
    ply_member: str | None = None
    colmap_dir: str | None = None
    colmap_format: Literal["bin", "txt"] | None = None
    lidar: LidarEvidence | None = None


def _point_cloud(stream: BinaryIO) -> InputDetection:
    """Đám mây điểm (PLY/PCD có x y z, không có thuộc tính 3DGS) là LiDAR đã đăng ký."""
    try:
        header = read_header(stream)
    except ValueError as error:
        raise InputRejectedError(f"File đám mây điểm không đọc được: {error}") from error
    return InputDetection(
        kind="registered_lidar",
        lidar=LidarEvidence(geometry_format=header.geometry_format, point_count=header.point_count),
    )


def _is_gaussian_header(stream: BinaryIO) -> bool:
    """PLY có opacity/scale/rotation là scene 3DGS; không có là đám mây điểm."""
    try:
        header = read_header(stream)
    except ValueError:
        return True  # để nhánh 3DGS báo lỗi đọc file như trước
    finally:
        stream.seek(0)
    return bool({"opacity", "scale_0", "rot_0"} & set(header.fields))


def _pose_count(text: str) -> int | None:
    """Số pose nếu mọi dòng là TUM hợp lệ (8 số hữu hạn, quaternion chuẩn hoá); None nếu không phải quỹ đạo."""
    count = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        if len(parts) != 8:
            return None
        try:
            values = [float(part) for part in parts]
        except ValueError:
            return None
        if (
            not all(math.isfinite(value) for value in values)
            or abs(math.hypot(*values[4:]) - 1) > _QUATERNION_TOLERANCE
        ):
            return None
        count += 1
    return count or None


def _detect_scan_sequence(archive: zipfile.ZipFile, names: list[str], scans: list[str]) -> InputDetection:
    """ZIP gồm nhiều scan `.pcd` và đúng một file quỹ đạo TUM (ADR 0009: scan thô phải đi kèm quỹ đạo)."""
    trajectories: list[tuple[str, int]] = []
    for name in names:
        info = archive.getinfo(name)
        if PurePosixPath(name).suffix.lower() not in _TRAJECTORY_SUFFIXES or info.file_size > _MAX_TRAJECTORY_BYTES:
            continue
        try:
            poses = _pose_count(archive.read(name).decode("ascii"))
        except UnicodeDecodeError:
            continue
        if poses is not None:
            trajectories.append((name, poses))
    if len(scans) == 1 and not trajectories:
        raise InputRejectedError(
            "ZIP chỉ có một file .pcd và không có quỹ đạo. Nếu đây là đám mây LiDAR đã đăng ký, tải thẳng file "
            ".pcd/.ply (không nén). Chuỗi scan thô cần nhiều scan kèm một file quỹ đạo."
        )
    if not trajectories:
        raise InputRejectedError(NO_TRAJECTORY.format(scans=len(scans)))
    if len(trajectories) > 1:
        listed = ", ".join(sorted(name for name, _ in trajectories))
        raise InputRejectedError(f"ZIP có {len(trajectories)} file quỹ đạo ({listed}); chỉ giữ một file")
    if len(scans) < 2:
        raise InputRejectedError("Chuỗi scan cần ít nhất 2 file .pcd")
    trajectory, poses = trajectories[0]
    ordered = sorted(scans)
    for name in (ordered[0], ordered[-1]):
        with archive.open(name) as member:
            try:
                header = read_header(member)  # type: ignore[arg-type]
            except ValueError as error:
                raise InputRejectedError(f"Scan {PurePosixPath(name).name} không đọc được: {error}") from error
        if header.geometry_format != "pcd":
            raise InputRejectedError(f"Scan {PurePosixPath(name).name} có đuôi .pcd nhưng nội dung không phải PCD")
    stems = [PurePosixPath(name).stem for name in ordered]
    if all(stem.isdigit() for stem in stems) and len(set(map(int, stems))) == len(stems):
        if max(map(int, stems)) >= poses:
            raise InputRejectedError(
                f"Tên scan là chỉ số pose nhưng scan {max(map(int, stems))} vượt quá quỹ đạo ({poses} pose, tính từ 0)"
            )
        pairing: Literal["index_in_name", "sorted_order"] = "index_in_name"
    elif len(ordered) == poses:
        pairing = "sorted_order"
    else:
        raise InputRejectedError(
            f"Số scan ({len(ordered)}) khác số pose trong quỹ đạo ({poses}). Mỗi scan cần đúng một pose: đặt tên scan "
            "bằng chỉ số dòng của pose (vd. 000421.pcd), hoặc nộp số scan bằng số pose"
        )
    return InputDetection(
        kind="lidar_scan_sequence",
        lidar=LidarEvidence(
            geometry_format="pcd",
            scan_count=len(ordered),
            pose_count=poses,
            trajectory_member=trajectory,
            pairing=pairing,
        ),
    )


def _gaussian_evidence(stream: BinaryIO, size: int | None) -> GaussianPlyEvidence:
    """Header PLY phải là 3DGS; PLY chỉ có xyz là đám mây điểm (nhánh LiDAR), không phải 3DGS."""
    try:
        header = read_header(stream)
    except ValueError as error:
        raise InputRejectedError(f"File PLY không đọc được: {error}") from error
    fields = set(header.fields)
    if not set(GAUSSIAN_FIELDS) <= fields:
        raise InputRejectedError("PLY này là point cloud, không phải scene 3DGS (thiếu opacity/scale/rotation).")
    rest = sum(1 for name in header.fields if name.startswith("f_rest_"))
    if rest not in _SH_REST:
        raise InputRejectedError(f"Số hệ số màu f_rest ({rest}) không khớp bậc SH 0–3")
    if size is not None and header.encoding == "binary_little_endian":
        # File bị cắt dở (upload lỗi, export hỏng) phát hiện được ngay từ kích thước.
        record = struct.calcsize("<" + "".join(header.codes))
        if stream.tell() + record * header.point_count != size:
            raise InputRejectedError("Kích thước file PLY không khớp số Gaussian trong header (file bị cắt hoặc hỏng)")
    return GaussianPlyEvidence(gaussian_count=header.point_count, sh_degree=_SH_REST[rest], encoding=header.encoding)


def _is_video(head: bytes) -> bool:
    return len(head) >= 8 and head[4:8] in _QUICKTIME_ATOMS


def _safe_names(archive: zipfile.ZipFile, max_uncompressed: int) -> list[str]:
    infos = archive.infolist()
    if len(infos) > _MAX_ZIP_ENTRIES:
        raise InputRejectedError(f"ZIP có quá nhiều file (>{_MAX_ZIP_ENTRIES})")
    total = 0
    names: list[str] = []
    for info in infos:
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise InputRejectedError("ZIP chứa đường dẫn không an toàn")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise InputRejectedError("ZIP chứa symlink; hãy nén lại file thật")
        total += info.file_size
        if total > max_uncompressed:
            raise InputRejectedError("ZIP giải nén vượt dung lượng cho phép")
        if not info.is_dir() and not path.name.startswith(".") and "__MACOSX" not in path.parts:
            names.append(info.filename)
    return names


def _colmap_model(names: list[str]) -> tuple[str, Literal["bin", "txt"]]:
    """Đúng một thư mục chứa đủ cameras/images/points3D cùng dạng bin hoặc txt."""
    found: dict[tuple[str, str], set[str]] = {}
    for name in names:
        path = PurePosixPath(name)
        if path.stem in _COLMAP_FILES and path.suffix in {".bin", ".txt"}:
            found.setdefault((str(path.parent), path.suffix[1:]), set()).add(path.stem)
    models = [key for key, stems in found.items() if stems == set(_COLMAP_FILES)]
    if not models:
        raise InputRejectedError("ZIP thiếu model COLMAP (cần cameras, images, points3D dạng .bin hoặc .txt)")
    if len(models) > 1:
        raise InputRejectedError("ZIP có nhiều model COLMAP; chỉ giữ một thư mục sparse")
    directory, fmt = models[0]
    return directory, fmt  # type: ignore[return-value]


def _detect_zip(stream: BinaryIO, max_uncompressed: int) -> InputDetection:
    try:
        with zipfile.ZipFile(stream) as archive:
            names = _safe_names(archive, max_uncompressed)
            scans = [name for name in names if PurePosixPath(name).suffix.lower() == ".pcd"]
            if scans:
                return _detect_scan_sequence(archive, names, scans)
            plies = [name for name in names if PurePosixPath(name).suffix.lower() == ".ply"]
            colmap_dir, colmap_format = _colmap_model(names)
            # points3D.ply của COLMAP là point cloud; chỉ đếm PLY có thuộc tính 3DGS.
            gaussians: list[tuple[str, GaussianPlyEvidence]] = []
            for name in plies:
                with archive.open(name) as member:
                    try:
                        evidence = _gaussian_evidence(member, None)  # type: ignore[arg-type]
                    except InputRejectedError:
                        continue
                gaussians.append((name, evidence))
    except zipfile.BadZipFile as error:
        raise InputRejectedError("File ZIP hỏng hoặc không phải ZIP") from error
    if len(gaussians) != 1:
        raise InputRejectedError(f"ZIP cần đúng một file PLY 3DGS, tìm thấy {len(gaussians)}")
    name, evidence = gaussians[0]
    return InputDetection(
        kind="gaussian_ply_colmap",
        gaussian=evidence,
        ply_member=name,
        colmap_dir=colmap_dir,
        colmap_format=colmap_format,
    )


def detect_stream(stream: BinaryIO, size_bytes: int, max_uncompressed_bytes: int) -> InputDetection:
    """Nhận diện trên stream seek được (file cục bộ hoặc object đọc theo đoạn)."""
    head = stream.read(16)
    stream.seek(0)
    if head.startswith(b"ply"):
        if not _is_gaussian_header(stream):
            return _point_cloud(stream)
        return InputDetection(kind="gaussian_ply", gaussian=_gaussian_evidence(stream, size_bytes))
    if head.startswith((b"# .PCD", b"VERSION")):
        return _point_cloud(stream)
    if head.startswith(b"PK\x03\x04"):
        return _detect_zip(stream, max_uncompressed_bytes)
    if _is_video(head):
        return InputDetection(kind="rgb_video")
    raise InputRejectedError(
        "Không nhận diện được file. Hỗ trợ: video .mp4/.mov; scene 3DGS .ply hoặc .zip (PLY 3DGS + model COLMAP); "
        "LiDAR đã đăng ký .ply/.pcd hoặc .zip (scan .pcd + file quỹ đạo)"
    )


def detect_input(path: Path, max_uncompressed_bytes: int) -> InputDetection:
    """Nhận diện file cục bộ theo bytes: video, PLY 3DGS, ZIP (3DGS + COLMAP), đám mây LiDAR, ZIP scan + quỹ đạo."""
    with path.open("rb") as stream:
        return detect_stream(stream, path.stat().st_size, max_uncompressed_bytes)
