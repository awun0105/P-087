"""Nhận diện loại đầu vào theo nội dung file (ADR 0004 §1), không tin đuôi file.

Chỉ đọc header/danh mục; không giải nén hay parse toàn bộ payload. Kết quả là
bằng chứng để PRODUCT lưu cùng upload và worker chọn luồng. File không khớp loại
nào bị từ chối với lý do hiển thị được cho người dùng, không đoán.
"""

import struct
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.services.reconstruction.lidar.cloud_header import read_header

InputKind = Literal["rgb_video", "gaussian_ply", "gaussian_ply_colmap"]

#: Thuộc tính bắt buộc của một Gaussian (vị trí, màu SH bậc 0, opacity, scale, rotation).
GAUSSIAN_FIELDS = ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2") + tuple(
    f"rot_{index}" for index in range(4)
)
#: Số hệ số f_rest theo bậc SH 0..3 (3 kênh màu × (bậc+1)² − 1).
_SH_REST = {0: 0, 9: 1, 24: 2, 45: 3}
_QUICKTIME_ATOMS = {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip"}
_COLMAP_FILES = ("cameras", "images", "points3D")
_MAX_ZIP_ENTRIES = 20000


class InputRejectedError(ValueError):
    """File không thuộc loại được hỗ trợ; message hiển thị được cho người dùng."""


class GaussianPlyEvidence(BaseModel):
    """Header 3DGS đã kiểm: số Gaussian, bậc SH, encoding."""

    model_config = ConfigDict(extra="forbid")

    gaussian_count: int = Field(gt=0)
    sh_degree: int = Field(ge=0, le=3)
    encoding: str


class InputDetection(BaseModel):
    """Loại đầu vào + bằng chứng; `ply_member`/`colmap_dir` chỉ có với ZIP."""

    model_config = ConfigDict(extra="forbid")

    kind: InputKind
    gaussian: GaussianPlyEvidence | None = None
    ply_member: str | None = None
    colmap_dir: str | None = None
    colmap_format: Literal["bin", "txt"] | None = None


def _gaussian_evidence(stream: BinaryIO, size: int | None) -> GaussianPlyEvidence:
    """Header PLY phải là 3DGS; PLY chỉ có xyz là point cloud, không nhận."""
    try:
        header = read_header(stream)
    except ValueError as error:
        raise InputRejectedError(f"File PLY không đọc được: {error}") from error
    fields = set(header.fields)
    if not set(GAUSSIAN_FIELDS) <= fields:
        raise InputRejectedError(
            "PLY này là point cloud, không phải scene 3DGS (thiếu opacity/scale/rotation). "
            "LiDAR của người dùng chưa được hỗ trợ."
        )
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


def _detect_zip(path: Path, max_uncompressed: int) -> InputDetection:
    try:
        with zipfile.ZipFile(path) as archive:
            names = _safe_names(archive, max_uncompressed)
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


def detect_input(path: Path, max_uncompressed_bytes: int) -> InputDetection:
    """Nhận diện theo bytes: video MP4/MOV, PLY 3DGS, hoặc ZIP (PLY 3DGS + COLMAP)."""
    with path.open("rb") as stream:
        head = stream.read(16)
        stream.seek(0)
        if head.startswith(b"ply"):
            return InputDetection(kind="gaussian_ply", gaussian=_gaussian_evidence(stream, path.stat().st_size))
    if head.startswith(b"PK\x03\x04"):
        return _detect_zip(path, max_uncompressed_bytes)
    if _is_video(head):
        return InputDetection(kind="rgb_video")
    raise InputRejectedError(
        "Không nhận diện được file. Hỗ trợ: video .mp4/.mov, scene 3DGS .ply, hoặc .zip gồm PLY 3DGS + model COLMAP"
    )
