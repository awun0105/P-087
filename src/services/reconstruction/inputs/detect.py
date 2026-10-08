"""Nhận diện loại đầu vào theo nội dung file (ADR 0004 §1, ADR 0009 §1), không tin đuôi file.

Chỉ đọc header/danh mục; không giải nén hay parse toàn bộ payload. Kết quả là
bằng chứng để PRODUCT lưu cùng upload và worker chọn luồng. File không khớp loại
nào bị từ chối với lý do hiển thị được cho người dùng, không đoán.
"""

import json
import math
import struct
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.contracts.input_assembly import InputAssetFormat
from src.services.reconstruction.lidar.cloud_header import read_header

InputKind = Literal[
    "rgb_video", "gaussian_ply", "gaussian_ply_colmap", "gaussian_sog", "registered_lidar", "lidar_scan_sequence"
]

#: Thuộc tính bắt buộc của một Gaussian (vị trí, màu SH bậc 0, opacity, scale, rotation).
GAUSSIAN_FIELDS = ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2") + tuple(
    f"rot_{index}" for index in range(4)
)
#: Số hệ số f_rest theo bậc SH 0..3 (3 kênh màu × (bậc+1)² − 1).
_SH_REST = {0: 0, 9: 1, 24: 2, 45: 3}
_QUICKTIME_ATOMS = {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip"}
_COLMAP_FILES = ("cameras", "images", "points3D")
_MAX_ZIP_ENTRIES = 20000
_MAX_SOG_TEXTURE_PIXELS = 64 * 1024 * 1024
_MAX_SOG_TEXTURE_BYTES = 256 * 1024 * 1024
# Only bundled SOG v2 is accepted. Limits are applied before reading texture contents.
SOG_FORMAT_REGISTRY = {
    2: {
        "models": (None, "antialiased", "2dgs"),
        "max_gaussians": 25_000_000,
        "max_meta_bytes": 64 * 1024,
        "max_members": 16,
    }
}
#: File quỹ đạo là văn bản nhỏ (một dòng mỗi pose); lớn hơn mức này không phải quỹ đạo.
_MAX_TRAJECTORY_BYTES = 16 * 1024 * 1024
_TRAJECTORY_SUFFIXES = {".txt", ".tum", ".csv"}
_QUATERNION_TOLERANCE = 1e-3
PACKAGE_GUIDE = (
    "Gói LiDAR là một file .zip gồm: (1) các scan .pcd chưa đăng ký, hoặc một đám mây .ply/.pcd đã đăng ký; "
    "(2) một file quỹ đạo dạng TUM — mỗi dòng `thời_điểm x y z qx qy qz qw`; "
    "(3) một file calibration camera ↔ LiDAR; (4) một file thời điểm frame — mỗi dòng một số, một dòng cho mỗi pose."
)
NO_TRAJECTORY = (
    "Tìm thấy {clouds} nhưng không có file quỹ đạo. Hệ thống không tự ước lượng quỹ đạo "
    "(LiDAR odometry/SLAM chưa hỗ trợ). " + PACKAGE_GUIDE
)
BARE_CLOUD = (
    "Đây là một đám mây điểm LiDAR ({points} điểm) nhưng nộp riêng lẻ thì không căn chỉnh được với video. "
    + PACKAGE_GUIDE
)
#: Khoá ngoại tham số camera trái ↔ LiDAR trong `calibrations.txt` của TorWIC.
_TORWIC_EXTRINSIC_KEYS = tuple(f"T_cam1_os.{name}" for name in ("px", "py", "pz", "qx", "qy", "qz", "qw"))


class InputRejectedError(ValueError):
    """File không thuộc loại được hỗ trợ; message hiển thị được cho người dùng."""


class GaussianPlyEvidence(BaseModel):
    """Header 3DGS đã kiểm: số Gaussian, bậc SH, encoding."""

    model_config = ConfigDict(extra="forbid")

    gaussian_count: int = Field(gt=0)
    sh_degree: int = Field(ge=0, le=3)
    encoding: str


class GaussianSogEvidence(BaseModel):
    """Bounded metadata evidence for a bundled PlayCanvas SOG source."""

    model_config = ConfigDict(extra="forbid")

    format_version: Literal[2]
    gaussian_count: int = Field(gt=0, le=25_000_000)
    sh_degree: int = Field(ge=0, le=3)
    model: Literal["antialiased", "2dgs"] | None = None


class LidarEvidence(BaseModel):
    """Bằng chứng gói LiDAR đã kiểm ở mức danh mục (ADR 0009); `ST-LIDAR-INGEST` mới đọc toàn bộ điểm.

    Gói luôn có quỹ đạo, calibration và thời điểm frame. Đám mây đã đăng ký: `cloud_member` + `point_count`.
    Chuỗi scan thô: `scan_count` + cách ghép scan ↔ pose.
    """

    model_config = ConfigDict(extra="forbid")

    geometry_format: Literal["ply", "pcd"]
    cloud_member: str | None = None
    point_count: int | None = Field(default=None, gt=0)
    scan_count: int | None = Field(default=None, gt=1)
    pose_count: int = Field(gt=1)
    trajectory_member: str
    calibration_member: str
    calibration_format: Literal["torwic_txt", "json"]
    frame_times_member: str
    #: `index_in_name`: tên scan là chỉ số dòng trong quỹ đạo (vd. 000421.pcd ↔ pose 421, cho phép nộp một phần scan);
    #: `sorted_order`: scan thứ i theo thứ tự tên ↔ pose thứ i (số lượng phải bằng nhau).
    pairing: Literal["index_in_name", "sorted_order"] | None = None


class InputDetection(BaseModel):
    """Loại đầu vào + bằng chứng; `ply_member`/`colmap_dir` chỉ có với ZIP 3DGS, `lidar` chỉ có với LiDAR."""

    model_config = ConfigDict(extra="forbid")

    kind: InputKind
    gaussian: GaussianPlyEvidence | None = None
    sog: GaussianSogEvidence | None = None
    ply_member: str | None = None
    colmap_dir: str | None = None
    colmap_format: Literal["bin", "txt"] | None = None
    lidar: LidarEvidence | None = None


def _reject_bare_cloud(stream: BinaryIO) -> None:
    """Đám mây điểm nộp riêng lẻ thiếu quỹ đạo và calibration nên không căn chỉnh được (ADR 0009, owner 02/10/2026)."""
    try:
        header = read_header(stream)
    except ValueError as error:
        raise InputRejectedError(f"File đám mây điểm không đọc được: {error}") from error
    raise InputRejectedError(BARE_CLOUD.format(points=f"{header.point_count:,}".replace(",", ".")))


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


def _frame_time_count(text: str) -> int | None:
    """Số dòng nếu file là dãy thời điểm tăng dần (một số hữu hạn mỗi dòng); None nếu không phải."""
    previous, count = -math.inf, 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            value = float(line)
        except ValueError:
            return None
        if not math.isfinite(value) or value <= previous:
            return None
        previous, count = value, count + 1
    return count or None


def _calibration_format(text: str) -> Literal["torwic_txt", "json"] | None:
    """Calibration camera ↔ LiDAR: `calibrations.txt` kiểu TorWIC, hoặc JSON có khoá `lidar_from_camera`."""
    if all(key in text for key in _TORWIC_EXTRINSIC_KEYS):
        return "torwic_txt"
    stripped = text.lstrip()
    if stripped.startswith("{") and '"lidar_from_camera"' in stripped:
        return "json"
    return None


def _exactly_one(found: list[str], what: str, missing: str) -> str:
    if not found:
        raise InputRejectedError(missing)
    if len(found) > 1:
        raise InputRejectedError(f"ZIP có {len(found)} file {what} ({', '.join(sorted(found))}); chỉ giữ một file")
    return found[0]


def _detect_lidar_package(archive: zipfile.ZipFile, names: list[str], clouds: list[str]) -> InputDetection:
    """ZIP LiDAR: scan thô hoặc một đám mây đã đăng ký, luôn kèm quỹ đạo + calibration + thời điểm frame."""
    trajectories: dict[str, int] = {}
    frame_times: dict[str, int] = {}
    calibrations: dict[str, Literal["torwic_txt", "json"]] = {}
    for name in names:
        info = archive.getinfo(name)
        if name in clouds or info.file_size > _MAX_TRAJECTORY_BYTES:
            continue
        if PurePosixPath(name).suffix.lower() not in _TRAJECTORY_SUFFIXES | {".json", ".yaml", ".yml"}:
            continue
        try:
            text = archive.read(name).decode("utf-8")
        except UnicodeDecodeError:
            continue
        calibration = _calibration_format(text)
        if calibration is not None:
            calibrations[name] = calibration
        elif (poses := _pose_count(text)) is not None:
            trajectories[name] = poses
        elif (times := _frame_time_count(text)) is not None:
            frame_times[name] = times
    described = f"{len(clouds)} scan LiDAR (.pcd)" if len(clouds) > 1 else "một đám mây điểm LiDAR"
    trajectory = _exactly_one(list(trajectories), "quỹ đạo", NO_TRAJECTORY.format(clouds=described))
    calibration_name = _exactly_one(
        list(calibrations),
        "calibration",
        "Gói LiDAR thiếu file calibration camera ↔ LiDAR (vd. calibrations.txt của TorWIC có các khoá T_cam1_os.*, "
        'hoặc JSON có khoá "lidar_from_camera"). Không có nó thì không biết camera nằm ở đâu so với LiDAR. '
        + PACKAGE_GUIDE,
    )
    poses = trajectories[trajectory]
    matching_times = [name for name, count in frame_times.items() if count == poses]
    if frame_times and not matching_times:
        counts = ", ".join(f"{name}: {count} dòng" for name, count in sorted(frame_times.items()))
        raise InputRejectedError(f"File thời điểm frame không khớp quỹ đạo ({poses} pose): {counts}")
    times_name = _exactly_one(
        matching_times,
        "thời điểm frame",
        "Gói LiDAR thiếu file thời điểm frame (vd. frame_times.txt: mỗi dòng một thời điểm, một dòng cho mỗi pose). "
        "Không có nó thì không biết frame nào của video ứng với pose nào. " + PACKAGE_GUIDE,
    )
    common = dict(
        pose_count=poses,
        trajectory_member=trajectory,
        calibration_member=calibration_name,
        calibration_format=calibrations[calibration_name],
        frame_times_member=times_name,
    )
    ordered = sorted(clouds)
    headers = {}
    for name in (ordered[0], ordered[-1]):
        with archive.open(name) as member:
            try:
                headers[name] = read_header(member)  # type: ignore[arg-type]
            except ValueError as error:
                raise InputRejectedError(f"{PurePosixPath(name).name} không đọc được: {error}") from error
        if {"opacity", "scale_0", "rot_0"} & set(headers[name].fields):
            raise InputRejectedError(f"{PurePosixPath(name).name} là scene 3DGS, không phải đám mây LiDAR")
    if len(ordered) == 1:
        header = headers[ordered[0]]
        return InputDetection(
            kind="registered_lidar",
            lidar=LidarEvidence(
                geometry_format=header.geometry_format,
                cloud_member=ordered[0],
                point_count=header.point_count,
                **common,
            ),
        )
    if any(PurePosixPath(name).suffix.lower() != ".pcd" for name in ordered):
        raise InputRejectedError(
            "Gói có nhiều file đám mây: scan thô phải là .pcd (mỗi scan một file); đám mây đã đăng ký thì chỉ nộp một file"
        )
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
        lidar=LidarEvidence(geometry_format="pcd", scan_count=len(ordered), pairing=pairing, **common),
    )


def _is_point_cloud_member(archive: zipfile.ZipFile, name: str) -> bool:
    """PLY trong ZIP là đám mây điểm (không phải 3DGS) khi header đọc được và không có thuộc tính Gaussian."""
    with archive.open(name) as member:
        try:
            header = read_header(member)  # type: ignore[arg-type]
        except ValueError:
            return False
    return not {"opacity", "scale_0", "rot_0"} & set(header.fields)


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


def _sog_files(meta: dict[str, object], key: str, count: int) -> list[str]:
    """Return safe, root-level filenames from one SOG-v2 property descriptor."""
    descriptor = meta.get(key)
    if not isinstance(descriptor, dict):
        raise InputRejectedError(f"SOG thiếu metadata {key}")
    files = descriptor.get("files")
    if not isinstance(files, list) or len(files) != count:
        raise InputRejectedError(f"Metadata SOG {key}.files không hợp lệ")
    result: list[str] = []
    for filename in files:
        if (
            not isinstance(filename, str)
            or not filename
            or PurePosixPath(filename).name != filename
            or "\\" in filename
            or filename in {".", ".."}
        ):
            raise InputRejectedError(f"Tên texture SOG không an toàn: {filename!r}")
        result.append(filename)
    if len(result) != len(set(result)):
        raise InputRejectedError(f"Metadata SOG {key}.files bị lặp")
    return result


def _sog_codebook(meta: dict[str, object], key: str) -> None:
    descriptor = meta.get(key)
    if not isinstance(descriptor, dict):
        raise InputRejectedError(f"SOG thiếu metadata {key}")
    values = descriptor.get("codebook")
    if (
        not isinstance(values, list)
        or len(values) != 256
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in values
        )
    ):
        raise InputRejectedError(f"Metadata SOG {key}.codebook cần 256 số hữu hạn")


def _detect_sog(archive: zipfile.ZipFile, max_uncompressed: int) -> InputDetection:
    """Validate SOG identity/metadata without decoding large WebP images."""
    registry = SOG_FORMAT_REGISTRY[2]
    infos = archive.infolist()
    if len(infos) > registry["max_members"]:
        raise InputRejectedError("SOG có quá nhiều thành viên")
    archive_names = [info.filename for info in infos if not info.is_dir()]
    if len(archive_names) != len(set(archive_names)):
        raise InputRejectedError("SOG có tên thành viên bị lặp")
    if "meta.json" not in archive_names:
        raise InputRejectedError("SOG thiếu meta.json ở thư mục gốc")
    meta_info = next(info for info in infos if info.filename == "meta.json")
    if meta_info.file_size <= 0 or meta_info.file_size > registry["max_meta_bytes"]:
        raise InputRejectedError("meta.json của SOG rỗng hoặc vượt 64 KiB")
    try:
        meta = json.loads(archive.read(meta_info))
    except (UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        raise InputRejectedError("meta.json của SOG không đọc được") from error
    if not isinstance(meta, dict):
        raise InputRejectedError("meta.json của SOG phải là object")
    version = meta.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version not in SOG_FORMAT_REGISTRY:
        raise InputRejectedError(f"Phiên bản SOG không được hỗ trợ: {version!r}; hiện hỗ trợ version 2")
    model = meta.get("model")
    if model not in registry["models"]:
        raise InputRejectedError(f"Model SOG không được hỗ trợ: {model!r}")
    count = meta.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or not 0 < count <= registry["max_gaussians"]:
        raise InputRejectedError(f"Số Gaussian trong SOG phải nằm trong 1..{registry['max_gaussians']:,}")

    means = meta.get("means")
    if not isinstance(means, dict):
        raise InputRejectedError("SOG thiếu metadata means")
    for axis in ("mins", "maxs"):
        values = means.get(axis)
        if (
            not isinstance(values, list)
            or len(values) != 3
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                for value in values
            )
        ):
            raise InputRejectedError(f"Metadata SOG means.{axis} cần ba số hữu hạn")
    minimums = means["mins"]
    maximums = means["maxs"]
    if any(minimum > maximum for minimum, maximum in zip(minimums, maximums, strict=True)):
        raise InputRejectedError("Metadata SOG means.mins không được vượt means.maxs")

    files = _sog_files(meta, "means", 2)
    for key in ("scales", "quats", "sh0"):
        files.extend(_sog_files(meta, key, 1))
    _sog_codebook(meta, "scales")
    _sog_codebook(meta, "sh0")
    shn = meta.get("shN")
    if shn is None:
        sh_degree = 0
    else:
        if not isinstance(shn, dict):
            raise InputRejectedError("Metadata SOG shN không hợp lệ")
        bands = shn.get("bands")
        sh_count = shn.get("count")
        if isinstance(bands, bool) or not isinstance(bands, int) or bands not in {1, 2, 3}:
            raise InputRejectedError("Metadata SOG shN.bands phải nằm trong 1..3")
        if isinstance(sh_count, bool) or not isinstance(sh_count, int) or not 1 <= sh_count <= 65536:
            raise InputRejectedError("Metadata SOG shN.count phải nằm trong 1..65536")
        _sog_codebook(meta, "shN")
        files.extend(_sog_files(meta, "shN", 2))
        sh_degree = bands

    expected = {"meta.json", *files}
    if len(expected) != len(files) + 1 or set(archive_names) != expected:
        raise InputRejectedError(
            "Gói SOG phải chứa đúng meta.json và texture được khai báo; không hỗ trợ file ngoài gói"
        )
    by_name = {info.filename: info for info in infos if not info.is_dir()}
    for filename in files:
        info = by_name.get(filename)
        if info is None or info.file_size <= 12:
            raise InputRejectedError(f"SOG thiếu texture hợp lệ: {filename}")
        try:
            with archive.open(info) as texture:
                signature = texture.read(12)
        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            raise InputRejectedError(f"Texture SOG không đọc được: {filename}") from error
        if len(signature) < 12 or signature[:4] != b"RIFF" or signature[8:12] != b"WEBP":
            raise InputRejectedError(f"Texture SOG không phải WebP: {filename}")
    if sum(info.file_size for info in infos) > max_uncompressed:
        raise InputRejectedError("SOG giải nén vượt dung lượng cho phép")
    return InputDetection(
        kind=InputAssetFormat.GAUSSIAN_SOG.value,
        sog=GaussianSogEvidence(format_version=2, gaussian_count=count, sh_degree=sh_degree, model=model),
    )


def _detect_zip(stream: BinaryIO, max_uncompressed: int) -> InputDetection:
    try:
        with zipfile.ZipFile(stream) as archive:
            names = _safe_names(archive, max_uncompressed)
            if "meta.json" in names:
                return _detect_sog(archive, max_uncompressed)
            plies = [name for name in names if PurePosixPath(name).suffix.lower() == ".ply"]
            clouds = [name for name in names if PurePosixPath(name).suffix.lower() == ".pcd"]
            has_colmap = any(PurePosixPath(name).stem in _COLMAP_FILES for name in names)
            if not has_colmap:
                clouds += [name for name in plies if _is_point_cloud_member(archive, name)]
            if clouds:
                return _detect_lidar_package(archive, names, clouds)
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
            _reject_bare_cloud(stream)
        return InputDetection(kind="gaussian_ply", gaussian=_gaussian_evidence(stream, size_bytes))
    if head.startswith((b"# .PCD", b"VERSION")):
        _reject_bare_cloud(stream)
    if head.startswith(b"PK\x03\x04"):
        return _detect_zip(stream, max_uncompressed_bytes)
    if _is_video(head):
        return InputDetection(kind="rgb_video")
    raise InputRejectedError(
        "Không nhận diện được file. Hỗ trợ: video .mp4/.mov; scene 3DGS .ply, .sog hoặc .zip (PLY 3DGS + model COLMAP); "
        "gói LiDAR .zip (scan .pcd hoặc đám mây đã đăng ký, kèm quỹ đạo + calibration + thời điểm frame)"
    )


def detect_input(path: Path, max_uncompressed_bytes: int) -> InputDetection:
    """Nhận diện file cục bộ theo bytes: video, PLY 3DGS, ZIP (3DGS + COLMAP), hoặc gói LiDAR .zip."""
    with path.open("rb") as stream:
        return detect_stream(stream, path.stat().st_size, max_uncompressed_bytes)


def validate_sog_bundle(path: Path, max_uncompressed_bytes: int) -> InputDetection:
    """Decode every bounded SOG WebP texture before a worker publishes the bundle."""
    detection = detect_input(path, max_uncompressed_bytes)
    if detection.kind != "gaussian_sog" or detection.sog is None:
        raise InputRejectedError("File nguồn không phải SOG v2 được hỗ trợ")
    try:
        with zipfile.ZipFile(path) as archive:
            meta = json.loads(archive.read("meta.json"))
            if not isinstance(meta, dict):
                raise InputRejectedError("Metadata SOG không hợp lệ")
            files: list[str] = []
            for key, count in (("means", 2), ("scales", 1), ("quats", 1), ("sh0", 1)):
                files.extend(_sog_files(meta, key, count))
            if meta.get("shN") is not None:
                files.extend(_sog_files(meta, "shN", 2))
            pixel_budget = min(
                _MAX_SOG_TEXTURE_PIXELS,
                max(1_000_000, detection.sog.gaussian_count * 12),
            )
            decoded_pixels = 0
            for filename in files:
                info = archive.getinfo(filename)
                if info.file_size > _MAX_SOG_TEXTURE_BYTES:
                    raise InputRejectedError(f"Texture SOG vượt giới hạn bytes: {filename}")
                encoded = archive.read(info)
                width, height, channels = _webp_dimensions_and_channels(encoded)
                pixels = width * height
                if (
                    width > 16_384
                    or height > 16_384
                    or pixels > pixel_budget
                    or decoded_pixels + pixels > pixel_budget
                    or channels not in {3, 4}
                ):
                    raise InputRejectedError(f"Kích thước hoặc số kênh texture SOG không hợp lệ: {filename}")
                decoded_pixels += pixels
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        raise InputRejectedError("Gói SOG không giải mã được") from error
    return detection


def _webp_dimensions_and_channels(payload: bytes) -> tuple[int, int, int]:
    """Read bounded WebP container dimensions/channels; the pinned runtime decodes pixels."""
    if len(payload) < 26 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
        raise InputRejectedError("Texture SOG không phải WebP hoàn chỉnh")
    if int.from_bytes(payload[4:8], "little") + 8 != len(payload):
        raise InputRejectedError("Kích thước RIFF/WebP không khớp bytes texture")
    offset = 12
    dimensions: tuple[int, int] | None = None
    channels: int | None = None
    while offset + 8 <= len(payload):
        chunk = payload[offset : offset + 4]
        size = int.from_bytes(payload[offset + 4 : offset + 8], "little")
        start = offset + 8
        end = start + size
        if end > len(payload):
            raise InputRejectedError("Chunk WebP vượt kích thước texture")
        data = payload[start:end]
        if chunk == b"VP8X" and size >= 10:
            dimensions = (
                1 + int.from_bytes(data[4:7], "little"),
                1 + int.from_bytes(data[7:10], "little"),
            )
            channels = 4 if data[0] & 0x10 else 3
        elif chunk == b"VP8 " and size >= 10 and data[3:6] == b"\x9d\x01\x2a":
            dimensions = (
                int.from_bytes(data[6:8], "little") & 0x3FFF,
                int.from_bytes(data[8:10], "little") & 0x3FFF,
            )
            channels = 3
        elif chunk == b"VP8L" and size >= 5 and data[0] == 0x2F:
            bits = int.from_bytes(data[1:5], "little")
            dimensions = (1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF))
            channels = 4 if (bits >> 28) & 0x1 else 3
        offset = end + (size & 1)
    if offset != len(payload) or dimensions is None or channels is None:
        raise InputRejectedError("Texture SOG thiếu chunk WebP có kích thước giải mã")
    width, height = dimensions
    if width < 1 or height < 1:
        raise InputRejectedError("Texture SOG có kích thước rỗng")
    return width, height, channels
