"""Bước chuẩn bị video upload với FFmpeg thật trên clip tổng hợp nhỏ (không cần GPU)."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import InputManifest, StageId
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction import prepare_cli
from src.services.reconstruction.prepare_cli import (
    IdempotentWriter,
    PrepareDependencies,
    VideoInputPreparer,
    frame_stride,
    target_frames,
)
from src.services.reconstruction.prepare_models import PrepareInputRequest
from src.services.reconstruction.rgb.frames.frame_extraction import FFmpegFrameDecoder
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.preflight.ffmpeg_probe import FFmpegRGBProbe
from src.services.reconstruction.rgb.preflight.quality import RGBQualityValidator
from src.services.reconstruction.rgb.preflight.quality_models import RGBQualityProfile

ROOT = Path(__file__).resolve().parents[2]
JOB = "job-prepare-test"
_ATTESTED = {"attested": True, "rights_to_use_confirmed": True, "anonymization_confirmed": True}


def _profile() -> RGBQualityProfile:
    payload: dict[str, object] = dict(
        schema_version="1.0",
        profile_id="test.prepare_v1",
        measurement_width=32,
        measurement_height=24,
        blur_exclude_gt=None,
        active_transition_px_gt=0.0,
        warn_active_ratio_lt=None,
        warn_static_run_gt=None,
        profile_checksum="sha256:" + "0" * 64,
    )
    payload["profile_checksum"] = canonical_content_checksum(payload, "profile_checksum")
    return RGBQualityProfile.model_validate(payload)


def _video(root: Path, source: str) -> Path:
    video = root / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", source, "-c:v", "mpeg4", str(video)],
        check=True,
    )
    return video


def _publish_input(store: FilesystemArtifactStore, video: Path, attestation: dict[str, object]) -> ProductArtifactRef:
    data = video.read_bytes()
    checksum = "sha256:" + hashlib.sha256(data).hexdigest()
    video_uri = f"artifact://jobs/{JOB}/input/clip.mp4"
    store.publish(
        ProductArtifactRef(
            artifact_type="RGBVideo",
            schema_version="1.0",
            artifact_uri=video_uri,
            artifact_checksum=checksum,
            data_class="product_input",
            producer_stage=StageId.INPUT_VALIDATE,
            job_id=JOB,
        ),
        data,
    )
    payload = InputManifest.model_validate_json(
        (ROOT / "fixtures/mock_job/input_manifest.json").read_text()
    ).model_dump(mode="json")
    payload.update(
        source_type="upload",
        files=[
            dict(
                original_name="clip.mp4",
                media_type="video/mp4",
                size_bytes=len(data),
                checksum=checksum,
                artifact_uri=video_uri,
                data_class="product_input",
            )
        ],
        source_rights_attestation=attestation,
        dataset_manifest_checksum=None,
        preparation_provenance=None,
    )
    payload["input_manifest_checksum"] = canonical_content_checksum(payload, "input_manifest_checksum")
    manifest = InputManifest.model_validate(payload)
    body = manifest.model_dump_json(indent=2).encode() + b"\n"
    reference = ProductArtifactRef(
        artifact_type="InputManifest",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{JOB}/input/input_manifest.json",
        artifact_checksum="sha256:" + hashlib.sha256(body).hexdigest(),
        data_class="product_input",
        producer_stage=StageId.INPUT_VALIDATE,
        job_id=JOB,
    )
    store.publish(reference, body)
    return reference


def _preparer(root: Path) -> tuple[VideoInputPreparer, ArtifactResolver, FilesystemArtifactStore]:
    resolver = ArtifactResolver(root / "artifacts")
    store = FilesystemArtifactStore(resolver)
    deps = PrepareDependencies(
        writer=IdempotentWriter(store, resolver.require),
        resolve_uri=resolver.resolve,
        require=resolver.require,
        validator=RGBQualityValidator(FFmpegRGBProbe()),
        decoder=FFmpegFrameDecoder(),
    )
    return VideoInputPreparer(deps), resolver, store


def _publish_image_input(
    store: FilesystemArtifactStore, image_paths: tuple[Path, ...], input_video: Path | None = None
) -> ProductArtifactRef:
    files = []
    for index, path in enumerate(image_paths):
        payload = path.read_bytes()
        checksum = "sha256:" + hashlib.sha256(payload).hexdigest()
        uri = f"artifact://jobs/{JOB}/input/frames/{path.name}"
        reference = ProductArtifactRef(
            artifact_type="RGBFrame",
            schema_version="1.0",
            artifact_uri=uri,
            artifact_checksum=checksum,
            data_class="product_input",
            producer_stage=StageId.INPUT_VALIDATE,
            job_id=JOB,
        )
        store.publish(reference, payload)
        files.append(
            dict(
                original_name=path.name,
                media_type="image/png" if path.suffix.lower() == ".png" else "image/jpeg",
                size_bytes=len(payload),
                checksum=checksum,
                artifact_uri=uri,
                data_class="product_input",
            )
        )
    if input_video is not None:
        data = input_video.read_bytes()
        checksum = "sha256:" + hashlib.sha256(data).hexdigest()
        uri = f"artifact://jobs/{JOB}/input/video/{input_video.name}"
        store.publish(
            ProductArtifactRef(
                artifact_type="RGBVideo",
                schema_version="1.0",
                artifact_uri=uri,
                artifact_checksum=checksum,
                data_class="product_input",
                producer_stage=StageId.INPUT_VALIDATE,
                job_id=JOB,
            ),
            data,
        )
        files.append(
            dict(
                original_name=input_video.name,
                media_type="video/mp4",
                size_bytes=len(data),
                checksum=checksum,
                artifact_uri=uri,
                data_class="product_input",
            )
        )
    payload = InputManifest.model_validate_json(
        (ROOT / "fixtures/mock_job/input_manifest.json").read_text()
    ).model_dump(mode="json")
    payload.update(
        source_type="dataset",
        files=files,
        source_rights_attestation=_ATTESTED,
        dataset_manifest_checksum="sha256:" + "c" * 64,
        preparation_provenance={
            "input_mode": "video_with_preextracted_image_refs" if input_video else "image_refs",
            "video_decode_skipped": input_video is not None,
        },
        video_preparation=None,
    )
    payload["input_manifest_checksum"] = canonical_content_checksum(payload, "input_manifest_checksum")
    manifest = InputManifest.model_validate(payload)
    body = manifest.model_dump_json(indent=2).encode() + b"\n"
    reference = ProductArtifactRef(
        artifact_type="InputManifest",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{JOB}/input/input_manifest.json",
        artifact_checksum="sha256:" + hashlib.sha256(body).hexdigest(),
        data_class="product_input",
        producer_stage=StageId.INPUT_VALIDATE,
        job_id=JOB,
    )
    store.publish(reference, body)
    return reference


def test_frame_stride_caps_frame_count() -> None:
    assert frame_stride(10, 240) == 1
    assert frame_stride(241, 240) == 2
    assert frame_stride(1800, 240) == 8


def test_target_frames_scale_with_duration_and_cap() -> None:
    """Video dài có nhiều frame hơn; trần max_frames và sàn 2 frame luôn giữ."""
    assert target_frames(60, 3, 300) == 180
    assert target_frames(600, 3, 300) == 300
    assert target_frames(0.2, 1, 300) == 2


def test_video_prepares_quality_privacy_and_strided_frame_set(tmp_path: Path) -> None:
    preparer, resolver, store = _preparer(tmp_path)
    manifest_ref = _publish_input(store, _video(tmp_path, "testsrc2=duration=2:size=32x24:rate=6"), _ATTESTED)
    request = PrepareInputRequest(
        job_id=JOB, input_manifest_ref=manifest_ref, quality_profile=_profile(), sample_fps=2, max_frames=50
    )
    result = preparer.run(request)
    assert result.error is None and result.frame_set_ref is not None
    assert result.extracted_frame_count == 4
    assert [stage.stage_id for stage in result.stage_artifacts] == [
        StageId.INPUT_VALIDATE,
        StageId.PRIVACY_GATE,
        StageId.FRAME_EXTRACT,
    ]
    # 12 frame, thời lượng 11/6 s × 2 fps → 4 frame mong muốn → cửa sổ 3 frame.
    assert result.selected_frame_count == 12 and result.frame_stride == 3
    assert result.video_duration_seconds is not None and 1.8 < result.video_duration_seconds < 1.9
    frames = FrameSetResolver(resolver.require, resolver.require).load(result.frame_set_ref)
    ids = [frame.frame_id for frame in frames.frames]
    assert len(ids) == 4 and all(window * 3 <= frame_id < window * 3 + 3 for window, frame_id in enumerate(ids))
    assert all(stage.started_at is not None and stage.completed_at is not None for stage in result.stage_artifacts)
    assert all(stage.started_at <= stage.completed_at for stage in result.stage_artifacts if stage.started_at)
    # Retry cùng job publish lại đúng bytes → idempotent, không kẹt ArtifactAlreadyExists.
    again = preparer.run(request)
    assert again.frame_set_ref == result.frame_set_ref


def test_dataset_preparation_uses_image_refs_and_never_decodes_input_video(tmp_path: Path) -> None:
    preparer, resolver, store = _preparer(tmp_path)
    source_video = _video(tmp_path, "testsrc2=duration=1:size=64x48:rate=4")
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source_video), str(image_dir / "%03d.png")],
        check=False,
    )
    assert result.returncode == 0
    images = tuple(sorted(image_dir.glob("*.png")))
    manifest_ref = _publish_image_input(store, images, source_video)
    source_video.unlink()
    manifest = InputManifest.model_validate_json(resolver.require(manifest_ref).read_bytes())
    assert any(item.media_type == "video/mp4" for item in manifest.files)
    assert len([item for item in manifest.files if item.media_type.startswith("image/")]) == len(images)
    request = PrepareInputRequest(job_id=JOB, input_manifest_ref=manifest_ref, quality_profile=_profile())
    prepared, _, _ = _preparer(tmp_path)

    class NoVideoDecoder(FFmpegFrameDecoder):
        def timestamps(self, video: Path) -> list[str]:
            raise AssertionError("dataset image preparation must not read a video")

        def decode(self, video: Path, output: Path, frame_ids: list[int] | None = None):
            raise AssertionError("dataset image preparation must not decode a video")

    prepared.deps = PrepareDependencies(
        writer=IdempotentWriter(FilesystemArtifactStore(resolver), resolver.require),
        resolve_uri=resolver.resolve,
        require=resolver.require,
        validator=RGBQualityValidator(FFmpegRGBProbe()),
        decoder=NoVideoDecoder(),
    )
    output = prepared.run(request)
    assert output.error is None and output.frame_set_ref is not None
    assert output.extracted_frame_count == len(images)
    frame_set = FrameSetResolver(resolver.require, resolver.require).load(output.frame_set_ref)
    for frame, source in zip(frame_set.frames, images, strict=True):
        assert (
            frame.image.artifact_uri
            == f"artifact://jobs/{frame.image.job_id}/rec02a/frames/{frame.frame_id:06d}{source.suffix}"
        )
        assert frame.image.artifact_checksum == "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()


def test_missing_attestation_stops_at_privacy_without_frames(tmp_path: Path) -> None:
    preparer, _, store = _preparer(tmp_path)
    attestation = {**_ATTESTED, "anonymization_confirmed": False}
    manifest_ref = _publish_input(store, _video(tmp_path, "testsrc2=duration=1:size=32x24:rate=4"), attestation)
    result = preparer.run(PrepareInputRequest(job_id=JOB, input_manifest_ref=manifest_ref, quality_profile=_profile()))
    assert result.frame_set_ref is None and result.error is not None
    assert result.error.stage_id == StageId.PRIVACY_GATE
    assert result.error.error_code == "PRIVACY_ATTESTATION_MISSING"
    assert [stage.status for stage in result.stage_artifacts] == ["SUCCEEDED", "FAILED"]


def test_static_video_fails_input_validation(tmp_path: Path) -> None:
    preparer, _, store = _preparer(tmp_path)
    manifest_ref = _publish_input(store, _video(tmp_path, "color=c=gray:size=32x24:rate=4:duration=1"), _ATTESTED)
    result = preparer.run(PrepareInputRequest(job_id=JOB, input_manifest_ref=manifest_ref, quality_profile=_profile()))
    assert result.error is not None and result.error.stage_id == StageId.INPUT_VALIDATE
    assert result.error.error_code == "RGB_STATIC_SEQUENCE"


def test_cli_prints_result_and_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, _, store = _preparer(tmp_path)
    manifest_ref = _publish_input(store, _video(tmp_path, "testsrc2=duration=1:size=32x24:rate=4"), _ATTESTED)
    request_path = tmp_path / "request.json"
    request_path.write_text(
        PrepareInputRequest(job_id=JOB, input_manifest_ref=manifest_ref, quality_profile=_profile()).model_dump_json()
    )
    code = prepare_cli.main(["--request", str(request_path), "--store-root", str(tmp_path / "artifacts")])
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0 and payload["result"]["frame_set_ref"]["artifact_type"] == "NormalizedRGBFrameSet"
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert prepare_cli.main(["--request", str(bad), "--store-root", str(tmp_path / "artifacts")]) == 2
