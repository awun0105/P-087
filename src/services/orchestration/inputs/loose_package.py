"""Đóng các file LiDAR nộp rời thành một gói chuẩn để dùng nguyên đường ingest/worker/QA của R4.

Người dùng không phải tự đóng ZIP: khi luồng R4 chạy, server gom các file đã bind (scan theo thứ tự người
dùng xác nhận, quỹ đạo, calibration, thời điểm frame) vào một ZIP có tên thành viên chuẩn, rồi cho gói đó đi
qua đúng bộ nhận diện của gói do người dùng nộp. Mọi thành viên ghi lại file nguồn và checksum nên bản
đóng gói truy vết ngược được; không có byte nào bị biến đổi.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import IO, TYPE_CHECKING

from src.models.contracts.input_assembly import InputAssetFormat, InputRole, StagedInputFile
from src.services.orchestration.projects.models import LidarPackageMember
from src.services.reconstruction.inputs.calibration_formats import CalibrationParseError, canonical_lidar_camera_json

if TYPE_CHECKING:  # Chỉ để chú thích: registry import module này nên không được kéo theo uploads/artifacts.
    from src.services.orchestration.artifacts.store import ArtifactResolver
    from src.services.orchestration.auth.models import Actor
    from src.services.orchestration.uploads.models import UploadRecord
    from src.services.orchestration.uploads.service import VideoUploadService

_CHUNK_BYTES = 1024 * 1024
PACKAGE_FILENAME = "lidar-package.zip"

_ROLE_NAMES = {
    InputRole.SENSOR_TRAJECTORY: "sensor_trajectory",
    InputRole.CAMERA_LIDAR_CALIBRATION: "camera_lidar_calibration",
    InputRole.RGB_FRAME_TIMES: "rgb_frame_times",
}


class LoosePackageError(ValueError):
    """Các file đã bind không đóng được thành gói LiDAR hợp lệ; thông điệp hiển thị được cho người dùng."""


def is_user_supplied_package(staged: Mapping[str, StagedInputFile], file_ids: list[str]) -> bool:
    """True khi mọi file đều là thành viên của đúng một ZIP người dùng đã nộp: giữ đường cũ, không đóng lại."""
    members = [staged[file_id] for file_id in file_ids]
    return (
        bool(members)
        and all(item.archive_member is not None for item in members)
        and (len({item.upload_id for item in members}) == 1)
    )


def verify_package_members(
    members: list[LidarPackageMember],
    *,
    staged: Mapping[str, StagedInputFile],
    role_bindings: Mapping[InputRole, list[str]],
    trajectory_member: str,
    calibration_member: str,
    frame_times_member: str,
    scan_count: int,
) -> None:
    """Gói do server đóng phải chứa đúng các file đã bind, nguyên vẹn, đúng vai trò và đúng thứ tự scan.

    Không đọc lại gói: bằng chứng là checksum nguồn đã niêm phong cùng assembly và tên thành viên khớp
    kết quả nhận diện của chính gói đó. Ném `LoosePackageError` khi có bất kỳ sai lệch nào.
    """
    expected_roles = {
        InputRole.SENSOR_TRAJECTORY: ("sensor_trajectory", trajectory_member),
        InputRole.CAMERA_LIDAR_CALIBRATION: ("camera_lidar_calibration", calibration_member),
        InputRole.RGB_FRAME_TIMES: ("rgb_frame_times", frame_times_member),
    }
    scans = role_bindings.get(InputRole.LIDAR_SCAN, [])
    if len(scans) != scan_count or len(members) != scan_count + len(expected_roles):
        raise LoosePackageError("Gói LiDAR do server đóng không khớp số file đã bind")
    by_file = {item.file_id: item for item in members}
    if len(by_file) != len(members):
        raise LoosePackageError("Gói LiDAR do server đóng có file trùng")
    for index, file_id in enumerate(scans):
        member = by_file.get(file_id)
        if member is None or member.role != "lidar_scan" or member.member_path != f"{index:06d}.pcd":
            raise LoosePackageError("Thứ tự scan trong gói không khớp thứ tự đã xác nhận")
    for role, (role_name, member_path) in expected_roles.items():
        ids = role_bindings.get(role, [])
        member = by_file.get(ids[0]) if len(ids) == 1 else None
        if member is None or member.role != role_name or member.member_path != member_path:
            raise LoosePackageError(f"Gói LiDAR thiếu hoặc nhầm thành viên {role_name}")
    for member in members:
        source = staged.get(member.file_id)
        if source is None:
            raise LoosePackageError("Gói LiDAR chứa file không thuộc assembly")
        expected = source.archive_member.member_checksum if source.archive_member else source.source_file.checksum
        if member.source_checksum != expected:
            raise LoosePackageError("Checksum thành viên không khớp file nguồn đã xác minh")


def _member_names(
    role_bindings: Mapping[InputRole, list[str]], staged: Mapping[str, StagedInputFile]
) -> list[tuple[str, str, str]]:
    """`(đường dẫn thành viên, file_id, vai trò)` theo đúng thứ tự gói; scan đánh số theo thứ tự đã xác nhận."""
    scans = role_bindings.get(InputRole.LIDAR_SCAN, [])
    if len(scans) < 2:
        raise LoosePackageError("Chuỗi scan cần ít nhất hai file")
    names: list[tuple[str, str, str]] = []
    for index, file_id in enumerate(scans):
        if staged[file_id].observed_format != InputAssetFormat.POINT_CLOUD_PCD:
            raise LoosePackageError("Scan thô nộp rời phải là file .pcd (mỗi scan một file)")
        names.append((f"{index:06d}.pcd", file_id, "lidar_scan"))
    for role in (InputRole.SENSOR_TRAJECTORY, InputRole.CAMERA_LIDAR_CALIBRATION, InputRole.RGB_FRAME_TIMES):
        ids = role_bindings.get(role, [])
        if len(ids) != 1:
            raise LoosePackageError(f"Cần đúng một file cho vai trò {_ROLE_NAMES[role]}")
        if role == InputRole.SENSOR_TRAJECTORY:
            name = "trajectory.txt"
        elif role == InputRole.RGB_FRAME_TIMES:
            name = "frame_times.txt"
        else:
            name = (
                "calibrations.txt"
                if staged[ids[0]].observed_format == InputAssetFormat.CALIBRATION_TORWIC_TEXT
                else "calibration.json"
            )
        names.append((name, ids[0], _ROLE_NAMES[role]))
    return names


def _expected_size(item: StagedInputFile) -> int:
    """Số byte thành viên sẽ có trong gói: kích thước giải nén đã niêm phong, hoặc kích thước file rời."""
    return item.archive_member.uncompressed_size_bytes if item.archive_member else item.source_file.size_bytes


def _source_bytes_path(item: StagedInputFile, resolver: ArtifactResolver) -> Path:
    return resolver.require_uri(item.source_file.artifact_uri, item.source_file.checksum)


_CALIBRATION_MAX_BYTES = 1024 * 1024


def _read_small(item: StagedInputFile, resolver: ArtifactResolver, limit: int) -> bytes:
    """Đọc cả file nhỏ (calibration) và kiểm checksum nguồn; lớn hơn `limit` thì từ chối."""
    source = _source_bytes_path(item, resolver)
    if item.archive_member is None:
        payload = source.read_bytes() if source.stat().st_size <= limit else b""
        expected = item.source_file.checksum
    else:
        if item.archive_member.uncompressed_size_bytes > limit:
            payload = b""
        else:
            try:
                with zipfile.ZipFile(source) as container:
                    payload = container.read(item.archive_member.member_path)
            except (zipfile.BadZipFile, KeyError) as error:
                raise LoosePackageError("Calibration trong ZIP đã tải lên không còn đọc được") from error
        expected = item.archive_member.member_checksum
    if not payload:
        raise LoosePackageError("File calibration rỗng hoặc lớn bất thường")
    if f"sha256:{hashlib.sha256(payload).hexdigest()}" != expected:
        raise LoosePackageError("File nguồn đã đổi so với lúc được xác minh; tải lại file đó")
    return payload


def _write_calibration(
    archive: zipfile.ZipFile,
    name: str,
    item: StagedInputFile,
    resolver: ArtifactResolver,
    lidar_frame_id: str | None,
) -> tuple[str, bool]:
    """Ghi calibration vào gói, chuẩn hoá về JSON `lidar_from_camera` khi bộ đọc gói chưa đọc được nguyên văn.

    Trả `(checksum nguồn, đã chuẩn hoá)`.
    """
    payload = _read_small(item, resolver, _CALIBRATION_MAX_BYTES)
    checksum = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    try:
        text = payload.decode("utf-8")
        canonical = canonical_lidar_camera_json(text, lidar_frame_id=lidar_frame_id)
    except (UnicodeDecodeError, CalibrationParseError) as error:
        raise LoosePackageError(f"Calibration không đọc được: {error}") from error
    body = payload if canonical is None else canonical.encode("utf-8")
    archive.writestr(name, body)
    return checksum, canonical is not None


def _write_member(archive: zipfile.ZipFile, name: str, item: StagedInputFile, resolver: ArtifactResolver) -> str:
    """Ghi một thành viên và trả checksum bytes đã ghi; sai lệch với checksum đã xác minh thì từ chối."""
    digest = hashlib.sha256()
    source = _source_bytes_path(item, resolver)
    limit = _expected_size(item)
    written = 0

    def copy(read: Callable[[int], bytes], target: IO[bytes]) -> None:
        nonlocal written
        for chunk in iter(lambda: read(_CHUNK_BYTES), b""):
            written += len(chunk)
            if written > limit:
                # ZIP của người dùng có thể khai kích thước nhỏ nhưng giải nén lớn: chặn ngay khi vượt khai báo.
                raise LoosePackageError("File nguồn lớn hơn kích thước đã xác minh; tải lại file đó")
            digest.update(chunk)
            target.write(chunk)

    if item.archive_member is None:
        with source.open("rb") as stream, archive.open(name, "w", force_zip64=True) as target:
            copy(stream.read, target)
        expected = item.source_file.checksum
    else:
        try:
            container = zipfile.ZipFile(source)
        except zipfile.BadZipFile as error:
            raise LoosePackageError("ZIP đã tải lên không còn đọc được; tải lại file đó") from error
        with container:
            try:
                member = container.open(item.archive_member.member_path)
            except KeyError as error:
                raise LoosePackageError("Thành viên đã bind không còn trong ZIP đã tải lên") from error
            with member, archive.open(name, "w", force_zip64=True) as target:
                copy(member.read, target)
        expected = item.archive_member.member_checksum
    actual = f"sha256:{digest.hexdigest()}"
    if actual != expected:
        raise LoosePackageError("File nguồn đã đổi so với lúc được xác minh; tải lại file đó")
    return actual


def synthesize_lidar_package(
    *,
    service: VideoUploadService,
    staged: Mapping[str, StagedInputFile],
    role_bindings: Mapping[InputRole, list[str]],
    uploaded_by: Actor | None,
    lidar_frame_id: str | None = None,
) -> tuple[UploadRecord, list[LidarPackageMember]]:
    """Đóng các file đã bind thành một gói LiDAR và nhận diện nó như gói người dùng nộp.

    Trả về bản ghi upload của gói (đã qua `detect_stream`, nên cùng bộ luật với gói tự nộp) và danh sách
    thành viên để ghi vào provenance. Nhận diện thất bại (ví dụ số scan lệch số pose) ném `UploadError`
    kèm thông điệp của bộ nhận diện.
    """
    plan = _member_names(role_bindings, staged)
    # Kiểm tổng dung lượng TRƯỚC khi đụng vào đĩa: gói lớn hơn giới hạn upload thì từ chối ngay, không đệm rồi mới hỏng.
    total = sum(_expected_size(staged[file_id]) for _, file_id, _ in plan)
    if total > service.max_bytes:
        raise LoosePackageError(
            f"Các file LiDAR cộng lại {total / 1e6:.0f} MB, vượt giới hạn {service.max_bytes / 1e6:.0f} MB của một gói"
        )
    pending = service.begin_assembly(PACKAGE_FILENAME)
    members: list[LidarPackageMember] = []
    try:
        with tempfile.TemporaryFile() as scratch:
            with zipfile.ZipFile(scratch, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for name, file_id, role in plan:
                    item = staged[file_id]
                    normalized = False
                    if role == "camera_lidar_calibration":
                        checksum, normalized = _write_calibration(archive, name, item, service.resolver, lidar_frame_id)
                    else:
                        checksum = _write_member(archive, name, item, service.resolver)
                    members.append(
                        LidarPackageMember(
                            member_path=name,
                            file_id=file_id,
                            source_checksum=checksum,
                            role=role,  # type: ignore[arg-type]
                            normalized=normalized,
                        )
                    )
            scratch.seek(0)
            shutil.copyfileobj(scratch, _PublicationWriter(pending.publication), _CHUNK_BYTES)
        record = service.finish(pending, uploaded_by)
    except BaseException:
        pending.publication.abort()
        raise
    return record, members


class _PublicationWriter:
    """Chuyển `write` của `StreamingPublication` thành file-like tối thiểu cho `shutil.copyfileobj`."""

    def __init__(self, publication: object) -> None:
        self._publication = publication

    def write(self, chunk: bytes) -> int:
        self._publication.write(chunk)  # type: ignore[attr-defined]
        return len(chunk)
