"""REC-02A frame inventory, privacy boundary và FFmpeg smoke."""

import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import InputManifest, PrivacyInspectionScope, PrivacyResult, StageId
from src.models.contracts.video_preparation import (
    ClientVideoPreparationManifest,
    ServerVideoPreparationVerification,
)
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.adapters.colmap_input import ColmapInputAdapter
from src.services.reconstruction.adapters.torwic_frame_source import TorwicFrameSource, TorwicFrameSourceConfig
from src.services.reconstruction.rgb.frames.frame_extraction import (
    ExtractionConfig,
    FFmpegFrameDecoder,
    FrameExtractionDependencies,
    FrameExtractionError,
    FrameExtractionRequest,
    RGBFrameExtractor,
)
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver, NormalizedRGBFrameSet
from src.services.reconstruction.rgb.preflight.privacy import (
    PrivacyDispatchProof,
    PrivacyInspectionEvidence,
    PrivacyQAAcceptance,
    PrivacyReviewRequest,
    RGBPrivacyGate,
)
from src.services.reconstruction.rgb.preflight.quality_models import (
    RGBFrameQuality,
    RGBMotionDiagnostics,
    RGBQualityReport,
)

ROOT = Path(__file__).parents[2]


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _manifest(paths: tuple[Path, ...], media_type: str) -> InputManifest:
    payload = InputManifest.model_validate_json(
        (ROOT / "fixtures/mock_job/input_manifest.json").read_text()
    ).model_dump(mode="json")
    payload["files"] = [
        dict(
            original_name=path.name,
            media_type=media_type,
            size_bytes=path.stat().st_size,
            checksum=_sha(path.read_bytes()),
            artifact_uri=f"artifact://jobs/rec02a-test/input/{path.name}",
            data_class="product_input",
        )
        for path in paths
    ]
    payload["input_manifest_checksum"] = canonical_content_checksum(payload, "input_manifest_checksum")
    return InputManifest.model_validate(payload)


def _quality(manifest: InputManifest, ids: tuple[int, ...], excluded: tuple[int, ...] = ()) -> RGBQualityReport:
    checksums = [file.checksum for file in manifest.files]
    if len(checksums) == 1:
        checksums *= len(ids)
    rows = [
        RGBFrameQuality(
            frame_id=frame_id,
            source_checksum=checksum,
            blur_score=1.0,
            quality="excluded" if frame_id in excluded else "accepted",
            reasons=["blur"] if frame_id in excluded else [],
        )
        for frame_id, checksum in zip(ids, checksums, strict=True)
    ]
    payload = dict(
        schema_version="1.0",
        source_manifest_checksum=manifest.input_manifest_checksum,
        selection_checksum="sha256:" + "a" * 64,
        profile_checksum="sha256:" + "b" * 64,
        ffmpeg_version="ffmpeg-test",
        producer_version="rec02-test",
        selected_frame_ids=list(ids),
        effective_reconstruction_frame_ids=[i for i in ids if i not in excluded],
        excluded_frame_ids=list(excluded),
        frames=[row.model_dump(mode="json") for row in rows],
        motion=RGBMotionDiagnostics(
            observed_transition_count=0,
            active_transition_count=0,
            max_static_run=0,
            max_selection_gap=0,
            fast_transition_frame_ids=[],
            warnings=[],
        ).model_dump(mode="json"),
        report_checksum="sha256:" + "0" * 64,
    )
    payload["report_checksum"] = canonical_content_checksum(payload, "report_checksum")
    return RGBQualityReport.model_validate(payload)


def _privacy(manifest: InputManifest, count: int) -> tuple[RGBPrivacyGate, PrivacyDispatchProof]:
    blank = PrivacyInspectionEvidence(
        PrivacyInspectionScope.ALL_SELECTED_FRAMES, count, count, (), "sha256:" + "0" * 64
    )
    evidence = PrivacyInspectionEvidence(
        PrivacyInspectionScope.ALL_SELECTED_FRAMES,
        count,
        count,
        (),
        canonical_content_checksum(asdict(blank), "evidence_checksum"),
    )
    acceptance = PrivacyQAAcceptance(
        manifest.input_manifest_checksum, evidence.evidence_checksum, "fixture-qa-acceptance"
    )
    gate = RGBPrivacyGate(lambda item: item == acceptance)
    report = gate.evaluate(PrivacyReviewRequest(manifest, evidence, acceptance))
    assert report.result == PrivacyResult.VERIFIED_ANONYMIZED
    return gate, PrivacyDispatchProof(report, evidence, acceptance)


def _config(mode: str) -> ExtractionConfig:
    payload = dict(
        schema_version="1.0",
        mode=mode,
        sampling_policy="quality_accepted",
        timestamp_policy="source_timestamp" if mode == "image_refs" else "source_pts",
        config_checksum="sha256:" + "0" * 64,
    )
    payload["config_checksum"] = canonical_content_checksum(payload, "config_checksum")
    return ExtractionConfig.model_validate(payload)


def _video_preparation_with_resolvable_map(tmp_path: Path):
    fixture = json.loads((ROOT / "fixtures/contracts/video_preparation_v1.json").read_text())
    rows = fixture["frame_map_rows"]
    sidecar = b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows)
    payload = fixture["preparation_manifest"]
    payload["frame_map"].update(size_bytes=len(sidecar), checksum=_sha(sidecar))
    payload["preparation_checksum"] = "sha256:" + "0" * 64
    payload["preparation_checksum"] = canonical_content_checksum(payload, "preparation_checksum")
    manifest = ClientVideoPreparationManifest.model_validate(payload)
    upload_id = "upload-frame-map-test"
    frame_map_ref = ProductArtifactRef(
        artifact_type="VideoFrameMap",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{upload_id}/input/video_frame_map.jsonl",
        artifact_checksum=manifest.frame_map.checksum,
        data_class=ArtifactDataClass.PRODUCT_INPUT,
        producer_stage=StageId.INPUT_VALIDATE,
        job_id=upload_id,
    )
    verification_payload = {
        "schema_version": "1.0",
        "status": "server_verified",
        "uploaded_checksum": manifest.prepared_file.checksum,
        "uploaded_size_bytes": manifest.prepared_file.size_bytes,
        "client_manifest": manifest.model_dump(mode="json"),
        "observed_video": manifest.prepared_video.model_dump(mode="json"),
        "frame_map_ref": frame_map_ref.model_dump(mode="json"),
        "original_source_status": "client_declared_unverified",
        "verification_checksum": "sha256:" + "0" * 64,
    }
    verification_payload["verification_checksum"] = canonical_content_checksum(
        verification_payload, "verification_checksum"
    )
    verification = ServerVideoPreparationVerification.model_validate(verification_payload)
    resolver = ArtifactResolver(tmp_path / "map_artifacts")
    FilesystemArtifactStore(resolver).publish(frame_map_ref, sidecar)
    return verification, resolver


def _service(
    root: Path, manifest: InputManifest, paths: tuple[Path, ...], gate: RGBPrivacyGate
) -> tuple[RGBFrameExtractor, ArtifactResolver]:
    resolver = ArtifactResolver(root / "artifacts")
    mapping = dict(zip((file.artifact_uri for file in manifest.files), paths, strict=True))
    dependencies = FrameExtractionDependencies(
        FilesystemArtifactStore(resolver), mapping.__getitem__, gate, FFmpegFrameDecoder()
    )
    return RGBFrameExtractor(dependencies), resolver


def test_image_refs_keep_source_frames_and_exclude_blur(tmp_path: Path) -> None:
    """Frame-set chỉ tham chiếu input frames; held-out không có trong manifest."""
    paths = tuple(tmp_path / f"{index:06d}.png" for index in range(3))
    for index, path in enumerate(paths):
        path.write_bytes(f"png-{index}".encode())
    manifest = _manifest(paths, "image/png")
    quality = _quality(manifest, (10, 11, 12), (11,))
    gate, proof = _privacy(manifest, 3)
    service, resolver = _service(tmp_path, manifest, paths, gate)
    request = FrameExtractionRequest(
        manifest, quality, proof, _config("image_refs"), "rec02a-test", {10: "0.1", 11: "0.2", 12: "0.3"}
    )
    result = service.execute(request)
    assert result.stage.status.value == "SUCCEEDED"
    assert [frame.frame_id for frame in result.frame_set.frames] == [10, 12]
    assert result.frame_set.frames[0].image.data_class == ArtifactDataClass.PRODUCT_INPUT
    mapping = {file.artifact_uri: path for file, path in zip(manifest.files, paths, strict=True)}
    reader = FrameSetResolver(lambda ref: mapping[ref.artifact_uri], resolver.require)
    loaded = reader.load(result.reference)
    assert reader.materialize(loaded) == ((10, paths[0], "0.1"), (12, paths[2], "0.3"))
    colmap_input = ColmapInputAdapter(reader).prepare(result.reference, tmp_path / "colmap")
    assert colmap_input.frame_ids == (10, 12)
    assert (colmap_input.image_dir / "000010.png").read_bytes() == paths[0].read_bytes()
    assert (colmap_input.image_dir / "000012.png").read_bytes() == paths[2].read_bytes()
    (colmap_input.image_dir / "000010.png").write_bytes(b"workspace changed")
    assert paths[0].read_bytes() == b"png-0"
    assert len(tuple((tmp_path / "artifacts").rglob("*.png"))) == 0


def test_privacy_and_timestamp_errors_publish_nothing(tmp_path: Path) -> None:
    """Incomplete QA/invalid timestamps cannot leave a success artifact."""
    paths = tuple(tmp_path / f"{i}.png" for i in range(2))
    for index, path in enumerate(paths):
        path.write_bytes(f"frame-{index}".encode())
    manifest = _manifest(paths, "image/png")
    quality = _quality(manifest, (0, 1))
    gate, proof = _privacy(manifest, 2)
    service, resolver = _service(tmp_path, manifest, paths, gate)
    bad_gate = RGBPrivacyGate(lambda item: False)
    blocked = RGBFrameExtractor(
        FrameExtractionDependencies(service.deps.writer, service.deps.resolve_input, bad_gate, service.deps.decoder)
    )
    request = FrameExtractionRequest(manifest, quality, proof, _config("image_refs"), "rec02a-test", {0: "0", 1: "1"})
    with pytest.raises(FrameExtractionError, match="REC-02 evidence"):
        blocked.execute(request)
    with pytest.raises(ValueError, match="timestamps"):
        service.execute(
            FrameExtractionRequest(manifest, quality, proof, request.config, "rec02a-test", {0: "1", 1: "0"})
        )
    assert not resolver.resolve("artifact://jobs/rec02a-test/rec02a/frame_set.json").exists()


def test_prepared_video_map_carries_source_indices_into_frame_set_input(tmp_path: Path) -> None:
    verification, resolver = _video_preparation_with_resolvable_map(tmp_path)
    service = RGBFrameExtractor(
        FrameExtractionDependencies(
            writer=None,  # This focused seam exercises only map loading and validation.
            resolve_input=lambda _: tmp_path,
            gate=None,
            decoder=None,
            resolve_product=resolver.require,
        )
    )
    request = FrameExtractionRequest(None, None, None, None, "frame-map-test", video_preparation=verification)
    decoded = SimpleNamespace(timestamps=["0", "0.0333333333", "0.0666666667"])
    chosen = [SimpleNamespace(frame_id=index) for index in range(3)]

    source_ids = service._source_frame_ids(request, chosen, decoded)

    assert source_ids == {0: 0, 1: 2, 2: 4}


def test_torwic_source_adapter_resolves_declared_inventory(tmp_path: Path) -> None:
    """REC-03 source resolver dùng inventory đã checksum, không path patch."""
    root = tmp_path / "dataset"
    frames = root / "normalized/aisle_cw/rgb_frames"
    frames.mkdir(parents=True)
    paths = tuple(frames / f"{i:06d}.png" for i in range(2))
    for index, path in enumerate(paths):
        path.write_bytes(f"frame-{index}".encode())
    manifest = _manifest(paths, "image/png")
    inventory = dict(
        input_manifest_checksum=manifest.input_manifest_checksum,
        frames=[
            dict(frame_id=i, artifact_uri=file.artifact_uri, checksum=file.checksum, size_bytes=file.size_bytes)
            for i, file in enumerate(manifest.files)
        ],
        inventory_checksum="sha256:" + "0" * 64,
    )
    inventory["inventory_checksum"] = canonical_content_checksum(inventory, "inventory_checksum")
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(inventory))
    source = TorwicFrameSource(TorwicFrameSourceConfig(root, "Aisle_CW", inventory_path), manifest)
    ref = ProductArtifactRef(
        artifact_type="RGBFrame",
        schema_version="1.0",
        artifact_uri=manifest.files[0].artifact_uri,
        artifact_checksum=manifest.files[0].checksum,
        data_class=ArtifactDataClass.PRODUCT_INPUT,
        producer_stage="ST-INPUT-VALIDATE",
    )
    assert source.resolve(ref) == paths[0]
    paths[0].write_bytes(b"changed")
    with pytest.raises(ValueError, match="differ"):
        source.resolve(ref)
    inventory["frames"][0]["checksum"] = "sha256:" + "0" * 64
    inventory_path.write_text(json.dumps(inventory))
    with pytest.raises(ValueError, match="checksum"):
        TorwicFrameSource(TorwicFrameSourceConfig(root, "Aisle_CW", inventory_path), manifest)


def test_preparation_quality_lineage_requires_declared_split(tmp_path: Path) -> None:
    """REC-01 preparation report chỉ gắn được qua provenance đã khai báo."""
    paths = tuple(tmp_path / f"{i:06d}.png" for i in range(2))
    for index, path in enumerate(paths):
        path.write_bytes(f"frame-{index}".encode())
    original = _manifest(paths, "image/png")
    quality = _quality(original, (0, 1))
    payload = original.model_dump(mode="json")
    payload["preparation_provenance"] = dict(
        preparation_manifest_checksum=original.input_manifest_checksum, split_checksum=quality.selection_checksum
    )
    payload["input_manifest_checksum"] = canonical_content_checksum(payload, "input_manifest_checksum")
    manifest = InputManifest.model_validate(payload)
    gate, proof = _privacy(manifest, 2)
    service, _ = _service(tmp_path, manifest, paths, gate)
    config = _config("image_refs")
    request = FrameExtractionRequest(manifest, quality, proof, config, "rec02a-lineage", {0: "0", 1: "1"})
    assert len(service.execute(request).frame_set.frames) == 2
    payload["preparation_provenance"]["split_checksum"] = "sha256:" + "f" * 64
    payload["input_manifest_checksum"] = canonical_content_checksum(payload, "input_manifest_checksum")
    changed = InputManifest.model_validate(payload)
    changed_gate, changed_proof = _privacy(changed, 2)
    blocked, _ = _service(tmp_path, changed, paths, changed_gate)
    with pytest.raises(FrameExtractionError, match="Quality mask"):
        blocked.execute(
            FrameExtractionRequest(changed, quality, changed_proof, config, "rec02a-blocked", {0: "0", 1: "1"})
        )


def test_real_ffmpeg_video_pts_and_resolver(tmp_path: Path) -> None:
    """Real FFmpeg 3-frame fixture có PTS và PNG payload kiểm checksum."""
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=1:size=32x24:rate=3",
            "-c:v",
            "mpeg4",
            str(video),
        ],
        check=True,
    )
    manifest = _manifest((video,), "video/mp4")
    quality = _quality(manifest, (0, 1, 2))
    gate, proof = _privacy(manifest, 3)
    service, resolver = _service(tmp_path, manifest, (video,), gate)
    result = service.execute(FrameExtractionRequest(manifest, quality, proof, _config("video_decode"), "rec02a-test"))
    reader = FrameSetResolver(resolver.require, resolver.require)
    assert isinstance(reader.load(result.reference), NormalizedRGBFrameSet)
    rows = reader.materialize(result.frame_set)
    assert [row[2] for row in rows] == ["0.000000", "0.333333", "0.666667"]
    assert all(path.read_bytes().startswith(b"\x89PNG") for _, path, _ in rows)
    assert len(rows) == 3


def _stride_config(stride: int | None, policy: str = "quality_accepted_stride") -> ExtractionConfig:
    payload: dict[str, object] = dict(
        schema_version="1.0",
        mode="video_decode",
        sampling_policy=policy,
        timestamp_policy="source_pts",
        config_checksum="sha256:" + "0" * 64,
    )
    if stride is not None:
        payload["frame_stride"] = stride
    payload["config_checksum"] = canonical_content_checksum(payload, "config_checksum")
    return ExtractionConfig.model_validate(payload)


def test_stride_config_binds_stride_and_keeps_legacy_checksum() -> None:
    """Config cũ không có stride vẫn hợp lệ; stride phải đi cùng policy stride."""
    assert _config("video_decode").frame_stride is None
    assert _stride_config(3).frame_stride == 3
    with pytest.raises(ValueError, match="frame_stride"):
        _stride_config(None)
    with pytest.raises(ValueError, match="frame_stride"):
        _stride_config(2, policy="quality_accepted")
    tampered = _stride_config(3).model_dump(mode="json")
    tampered["frame_stride"] = 4
    with pytest.raises(ValueError, match="checksum"):
        ExtractionConfig.model_validate(tampered)


def test_real_ffmpeg_video_stride_keeps_every_nth_accepted_frame(tmp_path: Path) -> None:
    """Stride áp lên frame đã qua quality, không lên index thô của video."""
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", "testsrc2=duration=2:size=32x24:rate=3", "-c:v", "mpeg4", str(video),
        ],
        check=True,
    )  # fmt: skip
    manifest = _manifest((video,), "video/mp4")
    quality = _quality(manifest, (0, 1, 2, 3, 4, 5), excluded=(3,))
    gate, proof = _privacy(manifest, 6)
    service, _ = _service(tmp_path, manifest, (video,), gate)
    result = service.execute(FrameExtractionRequest(manifest, quality, proof, _stride_config(2), "rec02a-test"))
    assert [frame.frame_id for frame in result.frame_set.frames] == [0, 2, 5]
    assert result.frame_set.extraction_config_checksum == _stride_config(2).config_checksum


def test_real_ffmpeg_sharpest_window_keeps_least_blurry_frame_per_window(tmp_path: Path) -> None:
    """Mỗi cửa sổ 3 frame đã qua quality giữ frame có blur_score thấp nhất (nét nhất)."""
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", "testsrc2=duration=2:size=32x24:rate=3", "-c:v", "mpeg4", str(video),
        ],
        check=True,
    )  # fmt: skip
    manifest = _manifest((video,), "video/mp4")
    quality = _quality(manifest, (0, 1, 2, 3, 4, 5))
    scores = {0: 3.0, 1: 1.0, 2: 2.0, 3: 5.0, 4: 5.0, 5: 4.0}
    payload = quality.model_dump(mode="json")
    for row in payload["frames"]:
        row["blur_score"] = scores[row["frame_id"]]
    payload["report_checksum"] = canonical_content_checksum(payload, "report_checksum")
    quality = RGBQualityReport.model_validate(payload)
    gate, proof = _privacy(manifest, 6)
    service, resolver = _service(tmp_path, manifest, (video,), gate)
    result = service.execute(
        FrameExtractionRequest(manifest, quality, proof, _stride_config(3, "quality_sharpest_window"), "rec02a-test")
    )
    assert [frame.frame_id for frame in result.frame_set.frames] == [1, 5]
    rows = FrameSetResolver(resolver.require, resolver.require).materialize(result.frame_set)
    assert [row[2] for row in rows] == ["0.333333", "1.666667"]


def test_selective_decode_matches_full_decode_bytes(tmp_path: Path) -> None:
    """Decode có chọn frame cho đúng pixel như decode toàn bộ tại cùng chỉ số."""
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", "testsrc2=duration=2:size=32x24:rate=4", "-c:v", "mpeg4", str(video),
        ],
        check=True,
    )  # fmt: skip
    decoder = FFmpegFrameDecoder()
    (tmp_path / "all").mkdir()
    (tmp_path / "some").mkdir()
    every = decoder.decode(video, tmp_path / "all")
    picked = decoder.decode(video, tmp_path / "some", [2, 5, 7])
    assert [path.read_bytes() for path in picked] == [every[i].read_bytes() for i in (2, 5, 7)]
    with pytest.raises(FrameExtractionError):
        decoder.decode(video, tmp_path / "some", [5, 2])
