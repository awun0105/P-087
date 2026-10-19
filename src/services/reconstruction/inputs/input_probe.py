"""Bounded content probes for staged files and safe ZIP members.

This module is the grouped-upload path. The legacy ``detect_stream`` contract
continues to reject loose point clouds until a complete legacy package exists.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from pydantic import BaseModel, ConfigDict

from src.models.contracts.input_assembly import (
    ArchiveMemberRef,
    InputAssetFormat,
    InputRole,
    InputRoleEvidence,
    StagedInputFile,
)
from src.models.contracts.manifests import InputFile
from src.services.reconstruction.inputs import calibration_formats, detect
from src.services.reconstruction.inputs.timestamps import (
    TimestampRowFormatError,
    TimestampRowValueError,
    parse_timestamp_rows,
)
from src.services.reconstruction.lidar.cloud_header import read_header

_MAX_ZIP_ENTRIES = 20_000
_MAX_TEXT_BYTES = 16 * 1024 * 1024
_MAX_HEADER_BYTES = 128 * 1024
_CHUNK_BYTES = 1024 * 1024
_QUATERNION_TOLERANCE = 1e-3


class InputProbe(BaseModel):
    """Ephemeral evidence for one exact staged reference; never substitutes for worker verification."""

    file_id: str
    source_checksum: str
    member_checksum: str | None
    observed_format: InputAssetFormat
    candidate_roles: tuple[InputRole, ...] = ()
    observed_roles: tuple[tuple[InputRole, str], ...] = ()
    record_count: int | None = None
    first_timestamp: float | None = None
    last_timestamp: float | None = None
    diagnostics: tuple[tuple[str, str, str], ...] = ()

    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True)
class ClassifiedUpload:
    """Deterministic staged files and probes produced from one authenticated upload ref."""

    files: tuple[StagedInputFile, ...]
    probes: tuple[InputProbe, ...]


@dataclass(frozen=True)
class _ContentResult:
    observed_format: InputAssetFormat
    candidate_roles: tuple[InputRole, ...] = ()
    observed_roles: tuple[tuple[InputRole, str], ...] = ()
    record_count: int | None = None
    first_timestamp: float | None = None
    last_timestamp: float | None = None
    diagnostic: tuple[str, str, str] | None = None


def classify_upload(
    source_file: InputFile,
    upload_id: str,
    file_id: str,
    path: Path,
    *,
    max_uncompressed_bytes: int,
) -> ClassifiedUpload:
    """Classify content without decoding geometry or trusting the uploaded filename."""
    if max_uncompressed_bytes < 1:
        raise ValueError("max_uncompressed_bytes must be positive")
    try:
        actual_size = path.stat().st_size
        if actual_size != source_file.size_bytes:
            return _invalid_upload(
                source_file,
                upload_id,
                file_id,
                "source_size_mismatch",
                "Uploaded bytes do not match the recorded size.",
            )
        with path.open("rb") as stream:
            return classify_upload_reader(
                source_file,
                upload_id,
                file_id,
                stream,
                suffix=path.suffix,
                max_uncompressed_bytes=max_uncompressed_bytes,
            )
    except (OSError, zipfile.BadZipFile, EOFError, NotImplementedError) as error:
        return _invalid_upload(
            source_file,
            upload_id,
            file_id,
            "unreadable_upload",
            f"Upload content could not be read ({type(error).__name__}).",
        )


def classify_upload_reader(
    source_file: InputFile,
    upload_id: str,
    file_id: str,
    stream: BinaryIO,
    *,
    suffix: str,
    max_uncompressed_bytes: int,
) -> ClassifiedUpload:
    """Classify a seekable verified source, including a remote range reader.

    This lets multipart uploads be probed from their immutable object without
    downloading a large video or point cloud into the API process.
    """
    if max_uncompressed_bytes < 1:
        raise ValueError("max_uncompressed_bytes must be positive")
    try:
        stream.seek(0)
        head = stream.read(16)
        if head.startswith(b"PK\x03\x04"):
            stream.seek(0)
            return _classify_zip(source_file, upload_id, file_id, stream, suffix, max_uncompressed_bytes)
        if suffix.lower() == ".sog":
            return _invalid_upload(
                source_file, upload_id, file_id, "invalid_sog", "A SOG upload must be a validated SOG v2 ZIP archive."
            )
        content = _read_probe_content(stream, source_file.size_bytes)
        result = _probe_content(
            content,
            source_file.size_bytes,
            text_probe_complete=source_file.size_bytes <= _MAX_TEXT_BYTES,
        )
        staged, probe = _make_staged(
            source_file,
            upload_id,
            file_id,
            result,
            member_checksum=None,
            member_path=None,
            member_size=None,
        )
        return ClassifiedUpload((staged,), (probe,))
    except (OSError, zipfile.BadZipFile, EOFError, NotImplementedError) as error:
        return _invalid_upload(
            source_file,
            upload_id,
            file_id,
            "unreadable_upload",
            f"Upload content could not be read ({type(error).__name__}).",
        )


def _classify_zip(
    source_file: InputFile,
    upload_id: str,
    file_id: str,
    stream: BinaryIO,
    suffix: str,
    max_uncompressed_bytes: int,
) -> ClassifiedUpload:
    with zipfile.ZipFile(stream) as archive:
        infos = _safe_inventory(archive, max_uncompressed_bytes)
        names = [info.filename for info in infos]
        root_meta = next((info for info in infos if info.filename == "meta.json"), None)
        sog_intent = suffix.lower() == ".sog"
        if root_meta is not None:
            sog_intent = sog_intent or _looks_like_sog(archive, root_meta)
        if sog_intent:
            try:
                stream.seek(0)
                detection = detect.detect_stream(stream, source_file.size_bytes, max_uncompressed_bytes)
            except detect.InputRejectedError as error:
                return _invalid_upload(source_file, upload_id, file_id, "invalid_sog", str(error))
            if detection.kind != "gaussian_sog":
                return _invalid_upload(
                    source_file,
                    upload_id,
                    file_id,
                    "invalid_sog",
                    "The archive declares a SOG scene but failed SOG v2 validation.",
                )
            result = _ContentResult(
                InputAssetFormat.GAUSSIAN_SOG,
                candidate_roles=(InputRole.GAUSSIAN_SCENE,),
                observed_roles=((InputRole.GAUSSIAN_SCENE, "sog_v2_metadata"),),
            )
            staged, probe = _make_staged(source_file, upload_id, file_id, result, None, None, None)
            return ClassifiedUpload((staged,), (probe,))

        member_results: list[tuple[zipfile.ZipInfo, str, _ContentResult]] = []
        for info in infos:
            member_checksum, prefix, text_content = _hash_member(archive, info, max_uncompressed_bytes)
            member_payload = text_content if text_content is not None else prefix
            result = _probe_content(member_payload, info.file_size, text_probe_complete=text_content is not None)
            member_results.append((info, member_checksum, result))

        gaussian_members = [
            (info, digest, result)
            for info, digest, result in member_results
            if result.observed_format == InputAssetFormat.GAUSSIAN_PLY
        ]
        colmap_dir: str | None = None
        colmap_format: str | None = None
        try:
            colmap_dir, colmap_format = detect._colmap_model(names)
        except detect.InputRejectedError:
            pass
        if colmap_dir == ".":
            colmap_dir = ""
        if len(gaussian_members) == 1 and colmap_dir is not None and colmap_format in {"bin", "txt"}:
            info, _member_checksum, _member_result = gaussian_members[0]
            used_names = {info.filename}
            for candidate in infos:
                parts = PurePosixPath(candidate.filename)
                candidate_dir = parts.parent.as_posix()
                if candidate_dir == ".":
                    candidate_dir = ""
                candidate_stem = parts.stem
                if candidate_dir == colmap_dir and candidate_stem in {"cameras", "images", "points3D"}:
                    used_names.add(candidate.filename)
            bundle_result = _ContentResult(
                InputAssetFormat.GAUSSIAN_PLY_COLMAP,
                candidate_roles=(InputRole.GAUSSIAN_SCENE,),
                observed_roles=((InputRole.GAUSSIAN_SCENE, "gaussian_ply_colmap_members"),),
            )
            staged: list[StagedInputFile] = []
            probes: list[InputProbe] = []
            root, probe = _make_staged(source_file, upload_id, file_id, bundle_result, None, None, None)
            staged.append(root)
            probes.append(probe)
            for extra_info, digest, result in member_results:
                if extra_info.filename in used_names:
                    continue
                member_id = _member_id(upload_id, extra_info.filename, digest)
                member_staged, member_probe = _make_staged(
                    source_file,
                    upload_id,
                    member_id,
                    result,
                    digest,
                    extra_info.filename,
                    extra_info.file_size,
                )
                staged.append(member_staged)
                probes.append(member_probe)
            return ClassifiedUpload(
                tuple(sorted(staged, key=lambda item: item.file_id)),
                tuple(sorted(probes, key=lambda item: item.file_id)),
            )

        staged, probes = [], []
        for info, digest, result in member_results:
            member_id = _member_id(upload_id, info.filename, digest)
            member_staged, member_probe = _make_staged(
                source_file,
                upload_id,
                member_id,
                result,
                digest,
                info.filename,
                info.file_size,
            )
            staged.append(member_staged)
            probes.append(member_probe)
        if not staged:
            return _invalid_upload(
                source_file, upload_id, file_id, "empty_archive", "The ZIP contains no file members."
            )
        return ClassifiedUpload(
            tuple(sorted(staged, key=lambda item: item.file_id)), tuple(sorted(probes, key=lambda item: item.file_id))
        )


def _safe_inventory(archive: zipfile.ZipFile, max_uncompressed_bytes: int) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > _MAX_ZIP_ENTRIES:
        raise zipfile.BadZipFile("archive has too many members")
    total = 0
    seen: set[str] = set()
    files: list[zipfile.ZipInfo] = []
    for info in infos:
        raw_name = info.filename
        path = PurePosixPath(raw_name)
        normalized = path.as_posix()
        allowed_directory_spelling = info.is_dir() and raw_name == f"{normalized}/"
        if (
            not raw_name
            or "\\" in raw_name
            or "\x00" in raw_name
            or raw_name.startswith("/")
            or any(part in {"", ".", ".."} for part in raw_name.rstrip("/").split("/"))
            or (normalized != raw_name and not allowed_directory_spelling)
            or (path.parts and ":" in path.parts[0])
        ):
            raise zipfile.BadZipFile("archive contains an unsafe member path")
        mode = info.external_attr >> 16
        if stat.S_IFMT(mode) == stat.S_IFLNK:
            raise zipfile.BadZipFile("archive contains a symbolic link")
        if info.flag_bits & 0x1:
            raise zipfile.BadZipFile("encrypted archive members are unsupported")
        if info.file_size < 0:
            raise zipfile.BadZipFile("archive has a negative member size")
        canonical = normalized.rstrip("/")
        if canonical in seen:
            raise zipfile.BadZipFile("archive contains duplicate member paths")
        seen.add(canonical)
        if info.is_dir():
            continue
        total += info.file_size
        if total > max_uncompressed_bytes:
            raise zipfile.BadZipFile("archive exceeds the configured expanded-size limit")
        files.append(info)
    return sorted(files, key=lambda item: item.filename)


def _looks_like_sog(archive: zipfile.ZipFile, meta_info: zipfile.ZipInfo) -> bool:
    if meta_info.file_size <= 0 or meta_info.file_size > 64 * 1024:
        return False
    try:
        metadata = json.loads(archive.read(meta_info))
    except (UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile):
        return False
    if not isinstance(metadata, dict):
        return False
    return bool({"means", "scales", "quats", "sh0", "shN"} & set(metadata)) or {
        "version",
        "model",
        "count",
    }.issubset(metadata)


def _hash_member(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, max_uncompressed_bytes: int
) -> tuple[str, bytes, bytes | None]:
    digest = hashlib.sha256()
    prefix = bytearray()
    captured_text: bytearray | None = None
    first_chunk = True
    actual = 0
    with archive.open(info) as member:
        while chunk := member.read(_CHUNK_BYTES):
            actual += len(chunk)
            if actual > max_uncompressed_bytes or actual > info.file_size:
                raise zipfile.BadZipFile("archive member expanded beyond its declared size")
            digest.update(chunk)
            if len(prefix) < _MAX_HEADER_BYTES:
                prefix.extend(chunk[: _MAX_HEADER_BYTES - len(prefix)])
            if first_chunk:
                if info.file_size <= _MAX_TEXT_BYTES and _text_prefix(bytes(prefix)):
                    captured_text = bytearray(chunk)
                first_chunk = False
            elif captured_text is not None and len(captured_text) < _MAX_TEXT_BYTES:
                captured_text.extend(chunk)
                if len(captured_text) > _MAX_TEXT_BYTES:
                    del captured_text[_MAX_TEXT_BYTES:]
    if actual != info.file_size:
        raise zipfile.BadZipFile("archive member size does not match its central directory")
    full_text = bytes(captured_text) if captured_text is not None and info.file_size <= _MAX_TEXT_BYTES else None
    return f"sha256:{digest.hexdigest()}", bytes(prefix), full_text


def _read_probe_content(stream: BinaryIO, size_bytes: int) -> bytes:
    stream.seek(0)
    prefix = stream.read(_MAX_HEADER_BYTES)
    if _text_prefix(prefix) and size_bytes <= _MAX_TEXT_BYTES:
        stream.seek(0)
        return stream.read(_MAX_TEXT_BYTES + 1)
    return prefix


def _probe_content(data: bytes, size_bytes: int, *, text_probe_complete: bool = True) -> _ContentResult:
    head = data[:16]
    if head.startswith(b"ply"):
        try:
            header = read_header(io.BytesIO(data))
            if {"opacity", "scale_0", "rot_0"} & set(header.fields):
                evidence = detect._gaussian_evidence(io.BytesIO(data), size_bytes)
                return _ContentResult(
                    InputAssetFormat.GAUSSIAN_PLY,
                    (InputRole.GAUSSIAN_SCENE,),
                    ((InputRole.GAUSSIAN_SCENE, "gaussian_ply_header"),),
                    evidence.gaussian_count,
                )
            return _ContentResult(InputAssetFormat.POINT_CLOUD_PLY, candidate_roles=_CLOUD_ROLES)
        except (ValueError, detect.InputRejectedError) as error:
            return _invalid_content(InputAssetFormat.UNKNOWN, "invalid_ply", str(error))
    if head.startswith((b"# .PCD", b"VERSION")):
        try:
            read_header(io.BytesIO(data))
            return _ContentResult(InputAssetFormat.POINT_CLOUD_PCD, candidate_roles=_CLOUD_ROLES)
        except ValueError as error:
            return _invalid_content(InputAssetFormat.UNKNOWN, "invalid_pcd", str(error))
    if detect._is_video(head):
        role = InputRole.RGB_VIDEO
        fmt = (
            InputAssetFormat.VIDEO_MOV if head[4:8] == b"ftyp" and head[8:12] == b"qt  " else InputAssetFormat.VIDEO_MP4
        )
        return _ContentResult(fmt, (role,), ((role, "quicktime_container_header"),))
    if _text_prefix(data):
        if size_bytes > _MAX_TEXT_BYTES and not text_probe_complete:
            return _invalid_content(
                InputAssetFormat.UNKNOWN, "text_probe_too_large", "Text metadata exceeds the 16 MiB probe limit."
            )
        return _probe_text(data)
    return _ContentResult(InputAssetFormat.UNKNOWN)


_CLOUD_ROLES = (InputRole.REGISTERED_LIDAR_MAP, InputRole.STATIC_LIDAR_CLOUD, InputRole.LIDAR_SCAN)


def _text_prefix(data: bytes) -> bool:
    if not data or b"\x00" in data[:4096]:
        return False
    sample = data[:4096]
    if sample.lstrip().startswith((b"{", b"[", b"#")):
        return True
    printable = sum(byte in (9, 10, 13) or 32 <= byte < 127 or byte >= 128 for byte in sample)
    return printable / len(sample) >= 0.9


def _probe_text(data: bytes) -> _ContentResult:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _ContentResult(InputAssetFormat.UNKNOWN)
    if "\x00" in text:
        return _ContentResult(InputAssetFormat.UNKNOWN)
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            value = json.loads(text, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            if "lidar_from_camera" in text or "camera_from_lidar" in text:
                return _invalid_content(
                    InputAssetFormat.UNKNOWN, "invalid_calibration_json", "Calibration JSON is malformed."
                )
            return _ContentResult(InputAssetFormat.UNKNOWN)
        if not isinstance(value, dict):
            return _ContentResult(InputAssetFormat.UNKNOWN)
        if "lidar_from_camera" in value and "camera_from_lidar" in value:
            return _invalid_content(
                InputAssetFormat.UNKNOWN,
                "ambiguous_calibration_direction",
                "Calibration declares both lidar_from_camera and camera_from_lidar; select one explicit transform convention.",
            )
        for key in ("lidar_from_camera", "camera_from_lidar"):
            if key in value:
                try:
                    calibration_formats.validate_calibration_structure(text)
                except calibration_formats.CalibrationParseError as error:
                    return _invalid_content(InputAssetFormat.UNKNOWN, "invalid_calibration_json", str(error))
                role = InputRole.CAMERA_LIDAR_CALIBRATION
                return _ContentResult(
                    InputAssetFormat.CALIBRATION_JSON,
                    (role,),
                    ((role, f"{key}_json_key"),),
                )
        return _ContentResult(InputAssetFormat.UNKNOWN)

    calibration_format = detect._calibration_format(text)
    if calibration_format == "json":
        role = InputRole.CAMERA_LIDAR_CALIBRATION
        return _ContentResult(InputAssetFormat.CALIBRATION_JSON, (role,), ((role, "lidar_from_camera_json_key"),))
    if calibration_format == "torwic_txt":
        tum_rows = _parse_tum_rows(text, allow_other_lines=True)
        if tum_rows is not None:
            return _invalid_content(
                InputAssetFormat.UNKNOWN,
                "ambiguous_text_roles",
                "One text file contains both calibration markers and TUM pose rows; split and bind the roles explicitly.",
            )
        role = InputRole.CAMERA_LIDAR_CALIBRATION
        return _ContentResult(
            InputAssetFormat.CALIBRATION_TORWIC_TEXT,
            (role,),
            ((role, "torwic_extrinsic_keys"),),
        )

    yaml_format = calibration_formats.detect_format(text)
    if yaml_format == "ros_transform_yaml":
        try:
            calibration_formats.validate_calibration_structure(text)
        except calibration_formats.CalibrationParseError as error:
            return _invalid_content(InputAssetFormat.UNKNOWN, "invalid_calibration_yaml", str(error))
        role = InputRole.CAMERA_LIDAR_CALIBRATION
        return _ContentResult(
            InputAssetFormat.CALIBRATION_ROS_YAML,
            (role,),
            ((role, "transform_stamped_yaml_keys"),),
        )
    if yaml_format == "kalibr_camchain":
        # Nhận ra để giải thích, không gán vai trò: Kalibr chỉ có camera ↔ IMU, không có LiDAR.
        return _ContentResult(
            InputAssetFormat.CALIBRATION_KALIBR_CAMCHAIN,
            diagnostic=(
                "kalibr_camera_imu_only",
                "warning",
                "File Kalibr chỉ có camera ↔ IMU và nội tham số camera, không có extrinsic LiDAR nên chưa dùng được "
                "làm calibration camera ↔ LiDAR.",
            ),
        )

    tum = _parse_tum_rows(text)
    if tum is not None:
        count, first, last, invalid = tum
        if invalid is not None:
            return _invalid_content(InputAssetFormat.UNKNOWN, "invalid_tum_trajectory", invalid)
        return _ContentResult(
            InputAssetFormat.TUM_TRAJECTORY,
            (InputRole.SENSOR_TRAJECTORY, InputRole.CAMERA_TRAJECTORY),
            record_count=count,
            first_timestamp=first,
            last_timestamp=last,
        )

    times = _parse_timestamp_rows(text)
    if times is not None:
        count, first, last, invalid = times
        if invalid is not None:
            return _invalid_content(InputAssetFormat.UNKNOWN, "invalid_timestamp_rows", invalid)
        return _ContentResult(
            InputAssetFormat.TIMESTAMP_ROWS,
            (InputRole.RGB_FRAME_TIMES, InputRole.LIDAR_SCAN_TIMES),
            (),
            count,
            first,
            last,
        )
    return _ContentResult(InputAssetFormat.UNKNOWN)


def _parse_tum_rows(
    text: str, *, allow_other_lines: bool = False
) -> tuple[int, float | None, float | None, str | None] | None:
    rows: list[list[float]] = []
    saw_pose_shape = False
    previous = -math.inf
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        if len(parts) != 8:
            if allow_other_lines:
                continue
            return None
        saw_pose_shape = True
        try:
            values = [float(part) for part in parts]
        except ValueError:
            return (0, None, None, "TUM rows must contain eight finite numbers.") if saw_pose_shape else None
        if not all(math.isfinite(value) for value in values):
            return 0, None, None, "TUM rows must contain eight finite numbers."
        if abs(math.hypot(*values[4:]) - 1) > _QUATERNION_TOLERANCE:
            return 0, None, None, "TUM pose quaternion is not normalized."
        if values[0] <= previous:
            return 0, None, None, "TUM timestamps must be strictly increasing."
        previous = values[0]
        rows.append(values)
    if not rows:
        return None
    if allow_other_lines and len(rows) == 0:
        return None
    return len(rows), rows[0][0], rows[-1][0], None


def _parse_timestamp_rows(text: str) -> tuple[int, float | None, float | None, str | None] | None:
    try:
        values = parse_timestamp_rows(text)
    except TimestampRowFormatError:
        return None
    except TimestampRowValueError as error:
        return 0, None, None, str(error)
    return len(values), values[0], values[-1], None


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _invalid_content(fmt: InputAssetFormat, code: str, message: str) -> _ContentResult:
    return _ContentResult(fmt, diagnostic=(code, "error", message))


def _member_id(upload_id: str, member_path: str, member_checksum: str) -> str:
    material = f"{upload_id}\0{member_path}\0{member_checksum}".encode()
    return f"member-{hashlib.sha256(material).hexdigest()[:40]}"


def _make_staged(
    source_file: InputFile,
    upload_id: str,
    file_id: str,
    result: _ContentResult,
    member_checksum: str | None,
    member_path: str | None,
    member_size: int | None,
) -> tuple[StagedInputFile, InputProbe]:
    member = None
    if member_path is not None and member_checksum is not None and member_size is not None:
        member = ArchiveMemberRef(
            container_checksum=source_file.checksum,
            member_path=member_path,
            member_checksum=member_checksum,
            uncompressed_size_bytes=member_size,
        )
    role_evidence = [
        InputRoleEvidence(role=role, provenance="observed", method=method) for role, method in result.observed_roles
    ]
    staged = StagedInputFile(
        file_id=file_id,
        upload_id=upload_id,
        source_file=source_file,
        observed_format=result.observed_format,
        archive_member=member,
        role_evidence=role_evidence,
    )
    diagnostics = () if result.diagnostic is None else (result.diagnostic,)
    probe = InputProbe(
        file_id=file_id,
        source_checksum=source_file.checksum,
        member_checksum=member_checksum,
        observed_format=result.observed_format,
        candidate_roles=result.candidate_roles,
        observed_roles=result.observed_roles,
        record_count=result.record_count,
        first_timestamp=result.first_timestamp,
        last_timestamp=result.last_timestamp,
        diagnostics=diagnostics,
    )
    return staged, probe


def _invalid_upload(source_file: InputFile, upload_id: str, file_id: str, code: str, message: str) -> ClassifiedUpload:
    result = _invalid_content(InputAssetFormat.UNKNOWN, code, message)
    staged, probe = _make_staged(source_file, upload_id, file_id, result, None, None, None)
    return ClassifiedUpload((staged,), (probe,))
