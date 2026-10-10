from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.models.contracts.input_assembly import (
    CandidateState,
    ClockRelation,
    CloudObservationState,
    EvidenceValue,
    InputAssemblySnapshot,
    InputBinding,
    InputResolutionState,
    InputRole,
    RecipeGroup,
    RuntimeCapabilityKey,
    RuntimeCapabilityRecord,
    RuntimeQualificationRegistry,
    RuntimeQualificationStatus,
    TrajectoryConvention,
    seal_input_assembly,
    seal_runtime_registry,
)
from src.models.contracts.manifests import InputFile
from src.services.reconstruction.inputs.detect import InputRejectedError, detect_stream
from src.services.reconstruction.inputs.input_probe import ClassifiedUpload, InputProbe, classify_upload
from src.services.reconstruction.inputs.input_resolver import resolve_input_assembly
from tests.test_reconstruction.support.sog_fixtures import sog_archive

ZERO_CHECKSUM = "sha256:" + "0" * 64
MAX_EXPANDED = 32 * 1024 * 1024


def _source(path: Path) -> InputFile:
    data = path.read_bytes()
    return InputFile(
        original_name=path.name,
        media_type="application/octet-stream",
        size_bytes=len(data),
        checksum="sha256:" + hashlib.sha256(data).hexdigest(),
        artifact_uri=f"artifact://jobs/test/source/{path.name}",
        data_class="product_input",
    )


def _upload(path: Path, *, upload_id: str | None = None, file_id: str | None = None) -> ClassifiedUpload:
    return classify_upload(
        _source(path),
        upload_id or path.stem,
        file_id or f"file-{path.stem}",
        path,
        max_uncompressed_bytes=MAX_EXPANDED,
    )


def _video() -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2"


def _cloud_ply() -> bytes:
    return (
        b"ply\nformat ascii 1.0\nelement vertex 1\n"
        b"property float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n"
    )


def _gaussian_ply() -> bytes:
    fields = (
        "x",
        "y",
        "z",
        "f_dc_0",
        "f_dc_1",
        "f_dc_2",
        "opacity",
        "scale_0",
        "scale_1",
        "scale_2",
        "rot_0",
        "rot_1",
        "rot_2",
        "rot_3",
        *(f"f_rest_{index}" for index in range(45)),
    )
    header = "ply\nformat ascii 1.0\nelement vertex 1\n"
    header += "".join(f"property float {name}\n" for name in fields) + "end_header\n"
    return header.encode() + ("0 " * len(fields)).encode() + b"\n"


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return path


def _qualified(key: RuntimeCapabilityKey) -> RuntimeCapabilityRecord:
    return RuntimeCapabilityRecord(
        capability_key=key,
        status=RuntimeQualificationStatus.QUALIFIED,
        runtime_id=f"worker-{key.value.lower()}",
        runtime_version="1.0.0",
        qualification_evidence_checksum=ZERO_CHECKSUM,
    )


def _wired(key: RuntimeCapabilityKey) -> RuntimeCapabilityRecord:
    return RuntimeCapabilityRecord(
        capability_key=key,
        status=RuntimeQualificationStatus.WIRED_UNQUALIFIED,
        runtime_id=f"worker-{key.value.lower()}",
        runtime_version="1.0.0",
        reason_codes=["acceptance_pending"],
    )


def _registry(*records: RuntimeCapabilityRecord) -> RuntimeQualificationRegistry:
    return seal_runtime_registry(
        RuntimeQualificationRegistry(
            schema_version="1.0",
            registry_version="test-registry-v1",
            capabilities=list(records),
            registry_checksum=ZERO_CHECKSUM,
        )
    )


def _assembly(
    uploads: list[ClassifiedUpload],
    *,
    bindings: list[InputBinding] | None = None,
    declarations: dict[str, object] | None = None,
    intent: str | None = None,
    reverse_files: bool = False,
) -> tuple[InputAssemblySnapshot, list[InputProbe]]:
    files = [item for upload in uploads for item in upload.files]
    probes = [probe for upload in uploads for probe in upload.probes]
    files.sort(key=lambda item: item.file_id)
    probes.sort(key=lambda item: item.file_id)
    if reverse_files:
        files.reverse()
    assembly = seal_input_assembly(
        InputAssemblySnapshot(
            schema_version="1.0",
            assembly_id="assembly-test",
            revision=1,
            owner_id="user-test",
            created_at=datetime(2026, 10, 8, tzinfo=UTC),
            requested_intent=intent,
            files=files,
            bindings=bindings or [],
            declarations=declarations or {},
            assembly_checksum=ZERO_CHECKSUM,
        )
    )
    return assembly, probes


def _write(tmp_path: Path, name: str, payload: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def test_content_classifier_accepts_loose_cloud_without_weakening_legacy_detector(tmp_path: Path) -> None:
    path = _write(tmp_path, "cloud-with-video-suffix.mp4", _cloud_ply())
    classified = _upload(path)

    assert classified.files[0].observed_format.value == "point_cloud_ply"
    assert classified.files[0].role_evidence == []
    with pytest.raises(InputRejectedError, match="nộp riêng lẻ"):
        detect_stream(io.BytesIO(path.read_bytes()), path.stat().st_size, MAX_EXPANDED)


def test_zip_inventory_is_stable_and_keeps_hidden_unrelated_members(tmp_path: Path) -> None:
    first_path = _zip(
        tmp_path / "first.zip",
        {
            "cloud.pcd": b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n",
            ".DS_Store": b"private metadata",
        },
    )
    second_path = _zip(
        tmp_path / "second.zip",
        {
            ".DS_Store": b"private metadata",
            "cloud.pcd": first_path.read_bytes()[:0]
            + b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n",
        },
    )
    first = _upload(first_path, upload_id="same-upload")
    second = _upload(second_path, upload_id="same-upload")

    first_files = {item.archive_member.member_path: item for item in first.files if item.archive_member}
    second_files = {item.archive_member.member_path: item for item in second.files if item.archive_member}
    assert set(first_files) == {"cloud.pcd", ".DS_Store"}
    assert first_files.keys() == second_files.keys()
    assert first_files["cloud.pcd"].observed_format.value == "point_cloud_pcd"
    assert first_files[".DS_Store"].observed_format.value == "unknown"
    assert {item.file_id for item in first.files} == {item.file_id for item in second.files}


@pytest.mark.parametrize(
    "members",
    [
        {"../escape.pcd": b"bad"},
        {"a\\b.pcd": b"bad"},
    ],
)
def test_unsafe_zip_paths_fail_closed(tmp_path: Path, members: dict[str, bytes]) -> None:
    path = _zip(tmp_path / "unsafe.zip", members)
    classified = _upload(path)
    assert classified.files[0].observed_format.value == "unknown"
    assert classified.probes[0].diagnostics[0][0] == "unreadable_upload"


def test_truncated_zip_and_corrupt_sog_fail_closed(tmp_path: Path) -> None:
    truncated = _write(tmp_path, "truncated.zip", b"PK\x03\x04not-a-directory")
    assert _upload(truncated).probes[0].diagnostics[0][0] == "unreadable_upload"

    corrupt_sog = _write(tmp_path, "broken.sog", b"not a zip")
    assert _upload(corrupt_sog).probes[0].diagnostics[0][0] == "invalid_sog"


def test_sog_is_separate_from_generic_meta_webp_and_colmap_zip(tmp_path: Path) -> None:
    sog_path = _write(tmp_path, "scene.bin", sog_archive())
    sog_path.rename(tmp_path / "scene.zip")
    sog = _upload(tmp_path / "scene.zip")
    assert len(sog.files) == 1
    assert sog.files[0].observed_format.value == "gaussian_sog"

    generic = _zip(tmp_path / "generic.zip", {"meta.json": b'{"title":"demo"}', "texture.webp": b"RIFFxxxxWEBP"})
    generic_result = _upload(generic)
    assert all(item.observed_format.value != "gaussian_sog" for item in generic_result.files)

    colmap = _zip(
        tmp_path / "colmap.zip",
        {
            "model/cameras.bin": b"cameras",
            "model/images.bin": b"images",
            "model/points3D.bin": b"points",
            "model/scene.ply": _gaussian_ply(),
        },
    )
    colmap_result = _upload(colmap)
    assert any(item.observed_format.value == "gaussian_ply_colmap" for item in colmap_result.files)

    root_colmap = _zip(
        tmp_path / "root-colmap.zip",
        {
            "cameras.bin": b"cameras",
            "images.bin": b"images",
            "points3D.bin": b"points",
            "scene.ply": _gaussian_ply(),
        },
    )
    root_result = _upload(root_colmap)
    assert len(root_result.files) == 1
    assert root_result.files[0].observed_format.value == "gaussian_ply_colmap"


def test_sog_validator_rejects_unsupported_versions(tmp_path: Path) -> None:
    path = _write(tmp_path, "unsupported.sog", sog_archive(version=3))
    classified = _upload(path)
    assert classified.probes[0].diagnostics[0][0] == "invalid_sog"


def test_text_probes_detect_trajectory_times_and_ambiguous_calibration(tmp_path: Path) -> None:
    frame_times = _upload(_write(tmp_path, "anything.dat", b"0.0\n0.1\n0.2\n"))
    assert frame_times.files[0].observed_format.value == "timestamp_rows"
    assert set(frame_times.probes[0].candidate_roles) == {InputRole.RGB_FRAME_TIMES, InputRole.LIDAR_SCAN_TIMES}
    assert frame_times.probes[0].observed_roles == ()
    assert frame_times.probes[0].record_count == 3

    tum_text = b"0 0 0 0 0 0 0 1\n1 1 0 0 0 0 0 1\n"
    tum = _upload(_write(tmp_path, "poses.csv", tum_text))
    assert tum.files[0].observed_format.value == "tum_trajectory"
    assert len(tum.files[0].role_evidence) == 0  # sensor/camera convention is not visible in TUM syntax

    invalid_times = _upload(_write(tmp_path, "times.txt", b"0\n2\n1\n"))
    assert invalid_times.probes[0].diagnostics[0][0] == "invalid_timestamp_rows"

    invalid_trajectory = _upload(_write(tmp_path, "poses.txt", b"0 0 0 0 0 0 0 1\n2 0 0 0 0 0 0 1\n1 0 0 0 0 0 0 1\n"))
    assert invalid_trajectory.probes[0].diagnostics[0][0] == "invalid_tum_trajectory"

    calibration = "\n".join(
        [
            "T_cam1_os.px: 0",
            "T_cam1_os.py: 0",
            "T_cam1_os.pz: 0",
            "T_cam1_os.qx: 0",
            "T_cam1_os.qy: 0",
            "T_cam1_os.qz: 0",
            "T_cam1_os.qw: 1",
            "0 0 0 0 0 0 0 1",
        ]
    ).encode()
    mixed = _upload(_write(tmp_path, "mixed.txt", calibration))
    assert mixed.probes[0].diagnostics[0][0] == "ambiguous_text_roles"

    both_directions = json.dumps({"lidar_from_camera": {}, "camera_from_lidar": {}}).encode()
    ambiguous_json = _upload(_write(tmp_path, "calibration.json", both_directions))
    assert ambiguous_json.probes[0].diagnostics[0][0] == "ambiguous_calibration_direction"


def test_probe_recognizes_ros_tf_calibration_and_reverse_json_and_explains_kalibr(tmp_path: Path) -> None:
    ros = _upload(
        _write(
            tmp_path,
            "tf.yaml",
            b"header:\n  frame_id: lidar\nchild_frame_id: cam\n"
            b"transform:\n  translation: {x: 0, y: 0, z: 0}\n  rotation: {x: 0, y: 0, z: 0, w: 1}\n",
        )
    )
    assert ros.files[0].observed_format.value == "calibration_ros_yaml"
    assert [item.role for item in ros.files[0].role_evidence] == [InputRole.CAMERA_LIDAR_CALIBRATION]

    reverse = _upload(_write(tmp_path, "calibration.json", b'{"camera_from_lidar":{"matrix":[]}}'))
    assert reverse.files[0].observed_format.value == "calibration_json"
    assert [item.role for item in reverse.files[0].role_evidence] == [InputRole.CAMERA_LIDAR_CALIBRATION]

    kalibr = _upload(
        _write(
            tmp_path,
            "camchain.yaml",
            b"cam0:\n  camera_model: pinhole\n  intrinsics: [1, 1, 0, 0]\n  T_cam_imu:\n  - [1, 0, 0, 0]\n",
        )
    )
    assert kalibr.files[0].observed_format.value == "calibration_kalibr_camchain"
    assert kalibr.files[0].role_evidence == []
    assert kalibr.probes[0].candidate_roles == ()
    assert kalibr.probes[0].diagnostics[0][:2] == ("kalibr_camera_imu_only", "warning")

    unknown = _upload(_write(tmp_path, "notes.yaml", b"title: not a calibration\nitems: [1, 2]\n"))
    assert unknown.files[0].observed_format.value == "unknown"


def test_video_only_qualified_runtime_resolves_ready_and_seals_report(tmp_path: Path) -> None:
    classified = _upload(_write(tmp_path, "renamed.bin", _video()))
    assembly, probes = _assembly([classified])
    report = resolve_input_assembly(assembly, _registry(_qualified(RuntimeCapabilityKey.R1)), probes)

    assert report.state == InputResolutionState.READY
    assert report.recommended_candidate_id is not None
    assert report.candidates[0].state == CandidateState.READY
    assert report.candidates[0].recipe_group == RecipeGroup.RGB_ONLY


def test_cloud_without_state_stays_ambiguous_and_report_is_order_independent(tmp_path: Path) -> None:
    video = _upload(_write(tmp_path, "video.mp4", _video()), upload_id="video-upload", file_id="video-file")
    cloud = _upload(_write(tmp_path, "cloud.ply", _cloud_ply()), upload_id="cloud-upload", file_id="cloud-file")
    assembly, probes = _assembly([video, cloud])
    reversed_assembly, reversed_probes = _assembly([video, cloud], reverse_files=True)
    registry = _registry(_qualified(RuntimeCapabilityKey.R2), _qualified(RuntimeCapabilityKey.R3))

    report = resolve_input_assembly(assembly, registry, probes)
    reordered = resolve_input_assembly(reversed_assembly, registry, reversed_probes)

    assert report.state == InputResolutionState.NEEDS_INPUT
    assert report.recommended_candidate_id is None
    assert {candidate.recipe_group for candidate in report.candidates if hasattr(candidate, "recipe_group")} == {
        RecipeGroup.REGISTERED_MAP,
        RecipeGroup.SINGLE_STATIC_CLOUD,
    }
    assert [candidate.candidate_id for candidate in report.candidates] == [
        candidate.candidate_id for candidate in reordered.candidates
    ]
    assert "CLOUD_STATE_REQUIRED" in {fact.code for fact in report.missing_facts}


def test_explicit_map_declarations_resolve_without_calibration_or_trajectory(tmp_path: Path) -> None:
    video = _upload(_write(tmp_path, "video.mp4", _video()), upload_id="video-upload", file_id="video-file")
    cloud = _upload(
        _write(
            tmp_path,
            "map.pcd",
            b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n",
        ),
        upload_id="cloud-upload",
        file_id="map-file",
    )
    declarations: dict[str, object] = {
        "cloud_state": EvidenceValue(value=CloudObservationState.REGISTERED_MAP, provenance="declared").model_dump(
            mode="json"
        ),
        "same_scene": EvidenceValue(value=True, provenance="declared").model_dump(mode="json"),
        "coordinate_unit": EvidenceValue(value="m", provenance="declared").model_dump(mode="json"),
        "lidar_frame_id": EvidenceValue(value="lidar_map", provenance="declared").model_dump(mode="json"),
    }
    assembly, probes = _assembly([video, cloud], declarations=declarations)
    report = resolve_input_assembly(assembly, _registry(_qualified(RuntimeCapabilityKey.R2)), probes)

    assert report.state == InputResolutionState.READY
    assert report.candidates[0].recipe_group == RecipeGroup.REGISTERED_MAP
    assert report.candidates[0].trajectory_origin.value == "not_required"


def test_mixed_video_and_gaussian_sources_require_intent_and_master_selection(tmp_path: Path) -> None:
    video = _upload(_write(tmp_path, "video.mp4", _video()), upload_id="video-upload", file_id="video-file")
    ply = _upload(_write(tmp_path, "scene.ply", _gaussian_ply()), upload_id="ply-upload", file_id="ply-file")
    sog = _upload(_write(tmp_path, "scene.sog", sog_archive()), upload_id="sog-upload", file_id="sog-file")
    assembly, probes = _assembly([video, ply, sog])
    registry = _registry(
        _qualified(RuntimeCapabilityKey.R1),
        _qualified(RuntimeCapabilityKey.GAUSSIAN_PLY_VIEW),
        _qualified(RuntimeCapabilityKey.GAUSSIAN_SOG_VIEW),
    )
    report = resolve_input_assembly(assembly, registry, probes)

    assert report.state == InputResolutionState.NEEDS_INPUT
    assert {"WORKFLOW_INTENT_REQUIRED", "GAUSSIAN_MASTER_SELECTION_REQUIRED"}.issubset(
        {fact.code for fact in report.missing_facts}
    )
    assert sum(candidate.candidate_kind == "gaussian_view_import" for candidate in report.candidates) == 2


def test_video_intent_with_gaussian_only_requests_a_video(tmp_path: Path) -> None:
    gaussian = _upload(_write(tmp_path, "scene.ply", _gaussian_ply()), upload_id="ply-upload", file_id="ply-file")
    assembly, probes = _assembly([gaussian], intent="video_reconstruction")

    report = resolve_input_assembly(assembly, _registry(_qualified(RuntimeCapabilityKey.R1)), probes)

    assert report.state == InputResolutionState.NEEDS_INPUT
    assert report.candidates == []
    assert "RGB_VIDEO_REQUIRED" in {fact.code for fact in report.missing_facts}


def test_raw_scan_order_is_never_inferred_from_member_names(tmp_path: Path) -> None:
    video = _upload(_write(tmp_path, "video.mp4", _video()), upload_id="video-upload", file_id="video-file")
    scan = b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n"
    scans = _upload(
        _zip(tmp_path / "scans.zip", {"scan_001.pcd": scan, "scan_002.pcd": scan}),
        upload_id="scan-upload",
        file_id="scan-archive",
    )
    assembly, probes = _assembly(
        [video, scans],
        declarations={
            "cloud_state": EvidenceValue(
                value=CloudObservationState.RAW_SCAN_SEQUENCE, provenance="declared"
            ).model_dump(mode="json")
        },
    )
    report = resolve_input_assembly(assembly, _registry(_wired(RuntimeCapabilityKey.R5)), probes)

    assert report.state == InputResolutionState.NEEDS_INPUT
    assert report.candidates[0].recipe_group == RecipeGroup.ESTIMATED_TRAJECTORY
    assert report.candidates[0].state == CandidateState.NEEDS_INPUT
    assert {"SCAN_SEQUENCE_ORDER_REQUIRED", "LIDAR_SCAN_TIMESTAMPS_REQUIRED"}.issubset(
        {fact.code for fact in report.missing_facts}
    )


def test_single_scan_cannot_enter_raw_scan_odometry_recipe(tmp_path: Path) -> None:
    video = _upload(_write(tmp_path, "video.mp4", _video()), upload_id="video-upload", file_id="video-file")
    scan = _upload(
        _write(
            tmp_path,
            "scan.pcd",
            b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n",
        ),
        upload_id="scan-upload",
        file_id="scan-file",
    )
    assembly, probes = _assembly(
        [video, scan],
        declarations={
            "cloud_state": EvidenceValue(
                value=CloudObservationState.RAW_SCAN_SEQUENCE, provenance="declared"
            ).model_dump(mode="json")
        },
    )

    report = resolve_input_assembly(assembly, _registry(_wired(RuntimeCapabilityKey.R5)), probes)

    assert "SCAN_SEQUENCE_NEEDS_MULTIPLE_FILES" in {fact.code for fact in report.missing_facts}
    assert not any(candidate.recipe_group == RecipeGroup.ESTIMATED_TRAJECTORY for candidate in report.candidates)


def test_one_timestamp_file_cannot_bind_both_rgb_and_lidar_roles(tmp_path: Path) -> None:
    video = _upload(_write(tmp_path, "video.mp4", _video()), upload_id="video-upload", file_id="video-file")
    scan = b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n"
    scans = _upload(
        _zip(tmp_path / "scans.zip", {"scan_001.pcd": scan, "scan_002.pcd": scan}),
        upload_id="scan-upload",
        file_id="scan-archive",
    )
    timestamps = _upload(
        _write(tmp_path, "timestamps.txt", b"0.0\n0.1\n"),
        upload_id="timestamps-upload",
        file_id="timestamps-file",
    )
    scan_ids = sorted(item.file_id for item in scans.files)
    assembly, probes = _assembly(
        [video, scans, timestamps],
        bindings=[
            InputBinding(binding_id="ordered-scans", role=InputRole.LIDAR_SCAN, file_ids=scan_ids),
            InputBinding(binding_id="rgb-times", role=InputRole.RGB_FRAME_TIMES, file_ids=["timestamps-file"]),
            InputBinding(binding_id="lidar-times", role=InputRole.LIDAR_SCAN_TIMES, file_ids=["timestamps-file"]),
        ],
        declarations={
            "cloud_state": EvidenceValue(
                value=CloudObservationState.RAW_SCAN_SEQUENCE, provenance="declared"
            ).model_dump(mode="json"),
        },
    )

    report = resolve_input_assembly(assembly, _registry(_wired(RuntimeCapabilityKey.R5)), probes)

    conflict = next(item for item in report.diagnostics if item.code == "TIMESTAMP_FILE_ROLE_CONFLICT")
    assert conflict.severity == "error"
    assert conflict.related_file_ids == ["timestamps-file"]


def test_r5_requires_exact_ordered_lidar_timestamps_and_stays_unqualified(tmp_path: Path) -> None:
    video = _upload(_write(tmp_path, "video.mp4", _video()), upload_id="video-upload", file_id="video-file")
    scan = b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n"
    scans = _upload(
        _zip(tmp_path / "scans.zip", {"scan_001.pcd": scan, "scan_002.pcd": scan}),
        upload_id="scan-upload",
        file_id="scan-archive",
    )
    scan_ids = sorted(item.file_id for item in scans.files)
    scan_times = _upload(
        _write(tmp_path, "sensor_times.txt", b"0.0\n0.1\n"),
        upload_id="times-upload",
        file_id="times-file",
    )
    declarations = {
        "cloud_state": EvidenceValue(value=CloudObservationState.RAW_SCAN_SEQUENCE, provenance="declared").model_dump(
            mode="json"
        ),
        "same_scene": EvidenceValue(value=True, provenance="declared").model_dump(mode="json"),
        "coordinate_unit": EvidenceValue(value="m", provenance="declared").model_dump(mode="json"),
        "lidar_frame_id": EvidenceValue(value="lidar", provenance="declared").model_dump(mode="json"),
        "lidar_timestamp_unit": EvidenceValue(value="seconds", provenance="declared").model_dump(mode="json"),
    }
    assembly, probes = _assembly(
        [video, scans, scan_times],
        bindings=[
            InputBinding(binding_id="ordered-scans", role=InputRole.LIDAR_SCAN, file_ids=scan_ids),
            InputBinding(binding_id="lidar-times", role=InputRole.LIDAR_SCAN_TIMES, file_ids=["times-file"]),
        ],
        declarations=declarations,
    )

    report = resolve_input_assembly(assembly, _registry(_wired(RuntimeCapabilityKey.R5)), probes)
    r5 = next(
        candidate for candidate in report.candidates if candidate.recipe_group == RecipeGroup.ESTIMATED_TRAJECTORY
    )

    assert report.state == InputResolutionState.PENDING_VERIFICATION
    assert r5.state == CandidateState.PENDING_VERIFICATION
    assert [binding.role for binding in r5.bindings] == [
        InputRole.RGB_VIDEO,
        InputRole.LIDAR_SCAN,
        InputRole.LIDAR_SCAN_TIMES,
    ]
    assert r5.runtime.status == RuntimeQualificationStatus.WIRED_UNQUALIFIED
    assert not r5.required_facts


def test_r5_timestamp_count_mismatch_blocks_the_estimated_recipe(tmp_path: Path) -> None:
    video = _upload(_write(tmp_path, "video.mp4", _video()), upload_id="video-upload", file_id="video-file")
    scan = b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n"
    scans = _upload(
        _zip(tmp_path / "scans.zip", {"scan_001.pcd": scan, "scan_002.pcd": scan}),
        upload_id="scan-upload",
        file_id="scan-archive",
    )
    scan_ids = sorted(item.file_id for item in scans.files)
    scan_times = _upload(_write(tmp_path, "sensor_times.txt", b"0.0\n"), upload_id="times-upload", file_id="times-file")
    assembly, probes = _assembly(
        [video, scans, scan_times],
        bindings=[
            InputBinding(binding_id="ordered-scans", role=InputRole.LIDAR_SCAN, file_ids=scan_ids),
            InputBinding(binding_id="lidar-times", role=InputRole.LIDAR_SCAN_TIMES, file_ids=["times-file"]),
        ],
        declarations={
            "cloud_state": EvidenceValue(
                value=CloudObservationState.RAW_SCAN_SEQUENCE, provenance="declared"
            ).model_dump(mode="json"),
            "same_scene": EvidenceValue(value=True, provenance="declared").model_dump(mode="json"),
            "coordinate_unit": EvidenceValue(value="m", provenance="declared").model_dump(mode="json"),
            "lidar_frame_id": EvidenceValue(value="lidar", provenance="declared").model_dump(mode="json"),
            "lidar_timestamp_unit": EvidenceValue(value="seconds", provenance="declared").model_dump(mode="json"),
        },
    )

    report = resolve_input_assembly(assembly, _registry(_qualified(RuntimeCapabilityKey.R5)), probes)
    r5 = next(
        candidate for candidate in report.candidates if candidate.recipe_group == RecipeGroup.ESTIMATED_TRAJECTORY
    )

    assert report.state == InputResolutionState.NEEDS_INPUT
    assert r5.state == CandidateState.NEEDS_INPUT
    assert "LIDAR_SCAN_TIMESTAMPS_COUNT_MISMATCH" in {fact.code for fact in r5.required_facts}


def test_r6_blocks_supplied_trajectory_with_mismatched_scan_count(tmp_path: Path) -> None:
    video = _upload(_write(tmp_path, "video.mp4", _video()), upload_id="video-upload", file_id="video-file")
    scan = b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n0 0 0\n"
    scans = _upload(
        _zip(tmp_path / "scans.zip", {"scan_001.pcd": scan, "scan_002.pcd": scan}),
        upload_id="scan-upload",
        file_id="scan-archive",
    )
    scan_ids_by_path = {item.archive_member.member_path: item.file_id for item in scans.files if item.archive_member}
    calibration = _upload(
        _write(tmp_path, "calibration.json", b'{"lidar_from_camera":{}}'),
        upload_id="calibration-upload",
        file_id="calibration-file",
    )
    trajectory = _upload(
        _write(tmp_path, "poses.tum", b"0 0 0 0 0 0 0 1\n"),
        upload_id="trajectory-upload",
        file_id="trajectory-file",
    )
    frame_times = _upload(
        _write(tmp_path, "frame-times.txt", b"0\n1\n"),
        upload_id="times-upload",
        file_id="times-file",
    )
    declarations: dict[str, object] = {
        "cloud_state": EvidenceValue(value=CloudObservationState.RAW_SCAN_SEQUENCE, provenance="declared").model_dump(
            mode="json"
        ),
        "same_scene": EvidenceValue(value=True, provenance="declared").model_dump(mode="json"),
        "coordinate_unit": EvidenceValue(value="m", provenance="declared").model_dump(mode="json"),
        "lidar_frame_id": EvidenceValue(value="lidar", provenance="declared").model_dump(mode="json"),
        "trajectory_convention": EvidenceValue(
            value=TrajectoryConvention.WORLD_FROM_SENSOR, provenance="declared"
        ).model_dump(mode="json"),
        "clock_relation": EvidenceValue(value=ClockRelation.SAME_CLOCK, provenance="declared").model_dump(mode="json"),
    }
    assembly, probes = _assembly(
        [video, scans, calibration, trajectory, frame_times],
        bindings=[
            InputBinding(
                binding_id="ordered-scans",
                role=InputRole.LIDAR_SCAN,
                file_ids=[scan_ids_by_path["scan_001.pcd"], scan_ids_by_path["scan_002.pcd"]],
            ),
            InputBinding(
                binding_id="sensor-trajectory", role=InputRole.SENSOR_TRAJECTORY, file_ids=["trajectory-file"]
            ),
            InputBinding(
                binding_id="camera-lidar-calibration",
                role=InputRole.CAMERA_LIDAR_CALIBRATION,
                file_ids=["calibration-file"],
            ),
            InputBinding(binding_id="rgb-frame-times", role=InputRole.RGB_FRAME_TIMES, file_ids=["times-file"]),
        ],
        declarations=declarations,
    )

    report = resolve_input_assembly(assembly, _registry(_qualified(RuntimeCapabilityKey.R6)), probes)
    r6 = next(
        candidate
        for candidate in report.candidates
        if getattr(candidate, "recipe_group", None) == RecipeGroup.SENSOR_GUIDED
    )

    assert report.state == InputResolutionState.NEEDS_INPUT
    assert r6.state == CandidateState.NEEDS_INPUT
    assert "SCAN_POSE_PAIRING_REQUIRED" in {fact.code for fact in r6.required_facts}
    r4 = next(candidate for candidate in report.candidates if candidate.recipe_group == RecipeGroup.SUPPLIED_TRAJECTORY)
    assert r4.state == CandidateState.NEEDS_INPUT
    codes = {fact.code for fact in r4.required_facts}
    # Gói do server tự đóng từ file rời nên không còn đòi ZIP; lý do chặn thật là số pose lệch số scan.
    assert "LIDAR_PACKAGE_REQUIRED" not in codes
    assert "SCAN_POSE_PAIRING_REQUIRED" in codes


def test_probe_identity_mismatch_is_invalid_and_unknown_content_is_unsupported(tmp_path: Path) -> None:
    video = _upload(_write(tmp_path, "video.mp4", _video()))
    assembly, probes = _assembly([video])
    tampered_probe = InputProbe(
        file_id=probes[0].file_id,
        source_checksum=ZERO_CHECKSUM,
        member_checksum=None,
        observed_format=probes[0].observed_format,
    )
    invalid = resolve_input_assembly(assembly, _registry(_qualified(RuntimeCapabilityKey.R1)), [tampered_probe])
    assert invalid.state == InputResolutionState.INVALID

    unknown = _upload(_write(tmp_path, "drawing.png", b"\x89PNG\r\n\x1a\nnot-a-supported-input"))
    unknown_assembly, unknown_probes = _assembly([unknown])
    unsupported = resolve_input_assembly(
        unknown_assembly, _registry(_qualified(RuntimeCapabilityKey.R1)), unknown_probes
    )
    assert unsupported.state == InputResolutionState.UNSUPPORTED
