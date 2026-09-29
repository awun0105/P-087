"""CLI ổn định cho bước chuẩn bị video upload: quality → privacy tự khai → frame set.

PRODUCT gọi qua process boundary (giống `preview_cli`), đọc kết quả JSON ở stdout
rồi ghi stage records vào JobManifest. Exit 0 = frame set sẵn sàng cho preview;
1 = stage failure có ExecutionError; 2 = request/setup/publication không hợp lệ.
"""

import argparse
import json
import logging
import math
import signal
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.artifacts import ArtifactDataClass, ArtifactRef, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import ExecutionError, InputManifest, StageArtifact, StageId, StageStatus
from src.services.reconstruction.prepare_models import PrepareInputRequest, PrepareInputResult
from src.services.reconstruction.rgb.frames.frame_extraction import (
    ExtractionConfig,
    FFmpegFrameDecoder,
    FrameExtractionDependencies,
    FrameExtractionError,
    FrameExtractionRequest,
    RGBFrameExtractor,
)
from src.services.reconstruction.rgb.preflight.ffmpeg_probe import FFmpegRGBProbe
from src.services.reconstruction.rgb.preflight.privacy import SelfAttestedPrivacyGate
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter, RGBPreflightPublisher
from src.services.reconstruction.rgb.preflight.quality import RGBQualityValidator, RGBValidationError, RGBVideoRequest
from src.services.reconstruction.rgb.preflight.quality_models import RGBQualityProfile

logger = logging.getLogger(__name__)

_VIDEO_MEDIA_TYPES = {"video/mp4", "video/quicktime"}


@dataclass(frozen=True)
class PrepareDependencies:
    """Composition root inject storage/tools; test thay bằng fake mà không đụng FFmpeg."""

    writer: ArtifactWriter
    resolve_uri: Callable[[str], Path]
    require: Callable[[ProductArtifactRef], Path]
    validator: RGBQualityValidator
    decoder: FFmpegFrameDecoder


def frame_stride(accepted_count: int, target: int) -> int:
    """Stride nhỏ nhất để số frame giữ lại không vượt `target`."""
    return max(1, math.ceil(accepted_count / target))


def target_frames(duration_seconds: float, sample_fps: float, max_frames: int) -> int:
    """Số frame mong muốn theo thời lượng; tối thiểu 2 frame, tối đa `max_frames`."""
    return max(2, min(max_frames, math.ceil(duration_seconds * sample_fps)))


def extraction_config(stride: int) -> ExtractionConfig:
    """Config video có checksum; stride 1 giữ mọi frame đã qua quality."""
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "mode": "video_decode",
        "sampling_policy": "quality_accepted" if stride == 1 else "quality_sharpest_window",
        "timestamp_policy": "source_pts",
        "config_checksum": "sha256:" + "0" * 64,
    }
    if stride > 1:
        payload["frame_stride"] = stride
    payload["config_checksum"] = canonical_content_checksum(payload, "config_checksum")
    return ExtractionConfig.model_validate(payload)


class VideoInputPreparer:
    """Một lần chuẩn bị cho một job; mỗi stage publish xong mới sang stage sau."""

    def __init__(self, deps: PrepareDependencies) -> None:
        self.deps = deps

    def run(self, request: PrepareInputRequest) -> PrepareInputResult:
        """Không bao giờ trả frame set khi quality/privacy thất bại."""
        manifest = self._manifest(request)
        stages: list[StageArtifact] = []
        publisher = RGBPreflightPublisher(self.deps.writer)
        try:
            video = self._video(manifest, request.quality_profile)
            quality = self.deps.validator.validate_video(video)
            quality_ref = publisher.publish_quality(quality, request.job_id)
            stages.append(_succeeded(StageId.INPUT_VALIDATE, quality_ref))
        except RGBValidationError as error:
            return self._failed(request, manifest, stages, error.to_execution_error())
        gate = SelfAttestedPrivacyGate()
        try:
            proof = gate.issue(manifest, len(quality.selected_frame_ids))
            privacy_ref = publisher.publish_privacy(proof.report, request.job_id)
            stages.append(_succeeded(StageId.PRIVACY_GATE, privacy_ref))
        except RGBValidationError as error:
            failure = error.to_execution_error().model_copy(update={"stage_id": StageId.PRIVACY_GATE})
            return self._failed(request, manifest, stages, failure)
        extractor = RGBFrameExtractor(
            FrameExtractionDependencies(self.deps.writer, self.deps.resolve_uri, gate, self.deps.decoder)
        )
        try:
            # PTS thật của video → thời lượng; lỗi PTS là lỗi của stage tách frame.
            timestamps = [float(value) for value in self.deps.decoder.timestamps(video.path)]
            duration = max(0.0, timestamps[-1] - timestamps[0])
            wanted = target_frames(duration, request.sample_fps, request.max_frames)
            stride = frame_stride(len(quality.effective_reconstruction_frame_ids), wanted)
            extracted = extractor.execute(
                FrameExtractionRequest(manifest, quality, proof, extraction_config(stride), request.job_id)
            )
        except FrameExtractionError as error:
            stages.append(error.to_failed_stage())
            return self._failed(request, manifest, stages, error.to_execution_error())
        stages.append(extracted.stage)
        return PrepareInputResult(
            job_id=request.job_id,
            input_manifest_checksum=manifest.input_manifest_checksum,
            stage_artifacts=stages,
            frame_set_ref=extracted.reference,
            frame_stride=stride,
            video_duration_seconds=duration,
            selected_frame_count=len(quality.selected_frame_ids),
            extracted_frame_count=len(extracted.frame_set.frames),
        )

    def _manifest(self, request: PrepareInputRequest) -> InputManifest:
        path = self.deps.require(request.input_manifest_ref)
        manifest = InputManifest.model_validate_json(path.read_bytes())
        verify_content_checksum(manifest, "input_manifest_checksum")
        return manifest

    def _video(self, manifest: InputManifest, profile: RGBQualityProfile) -> RGBVideoRequest:
        videos = [file for file in manifest.files if file.media_type in _VIDEO_MEDIA_TYPES]
        if len(videos) != 1 or len(manifest.files) != 1:
            raise RGBValidationError(
                "RGB_INPUT_SHAPE_UNSUPPORTED",
                "Upload preparation expects exactly one mp4/mov video",
                "Upload one moving-camera RGB video per scene",
            )
        file = videos[0]
        return RGBVideoRequest(
            path=self.deps.resolve_uri(file.artifact_uri),
            checksum=file.checksum,
            size_bytes=file.size_bytes,
            source_manifest_checksum=manifest.input_manifest_checksum,
            profile=profile,
        )

    @staticmethod
    def _failed(
        request: PrepareInputRequest,
        manifest: InputManifest,
        stages: list[StageArtifact],
        error: ExecutionError,
    ) -> PrepareInputResult:
        if not any(stage.stage_id == error.stage_id and stage.status == "FAILED" for stage in stages):
            stages.append(
                StageArtifact(
                    stage_id=error.stage_id,
                    status=StageStatus.FAILED,
                    completed_at=datetime.now(UTC),
                    error=error,
                )
            )
        logger.error("Prepare failed job=%s stage=%s code=%s", request.job_id, error.stage_id, error.error_code)
        return PrepareInputResult(
            job_id=request.job_id,
            input_manifest_checksum=manifest.input_manifest_checksum,
            stage_artifacts=stages,
            error=error,
        )


def _succeeded(stage_id: StageId, reference: ProductArtifactRef) -> StageArtifact:
    return StageArtifact(
        stage_id=stage_id,
        status=StageStatus.SUCCEEDED,
        artifact_type=reference.artifact_type,
        artifact_uri=reference.artifact_uri,
        artifact_checksum=reference.artifact_checksum,
        data_class=ArtifactDataClass.DERIVED,
        completed_at=datetime.now(UTC),
    )


class IdempotentWriter:
    """Retry cùng job có thể publish lại đúng bytes đã có; bytes khác vẫn bị chặn.

    Output quality/privacy/frame là deterministic theo input + config, nên chấp nhận
    artifact đã tồn tại khi checksum khớp giúp retry sau lỗi giữa chừng không kẹt.
    """

    def __init__(self, writer: ArtifactWriter, require: Callable[[ArtifactRef], Path]) -> None:
        self.writer = writer
        self.require = require

    def publish(self, reference: ArtifactRef, payload: bytes) -> ArtifactRef:
        """Publish mới, hoặc xác nhận artifact cũ có đúng checksum."""
        from src.services.orchestration.artifacts import ArtifactAlreadyExistsError

        try:
            return self.writer.publish(reference, payload)
        except ArtifactAlreadyExistsError:
            self.require(reference)  # ArtifactChecksumError nếu bytes cũ khác.
            return reference


def _execute(args: argparse.Namespace) -> int:
    # Chỉ composition root dùng storage facade; core nhận injected ports.
    from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore

    request = PrepareInputRequest.model_validate_json(args.request.read_bytes())
    resolver = ArtifactResolver(args.store_root)
    deps = PrepareDependencies(
        writer=IdempotentWriter(FilesystemArtifactStore(resolver), resolver.require),
        resolve_uri=resolver.resolve,
        require=resolver.require,
        validator=RGBQualityValidator(FFmpegRGBProbe()),
        decoder=FFmpegFrameDecoder(),
    )
    result = VideoInputPreparer(deps).run(request)
    print(json.dumps({"result": result.model_dump(mode="json")}))
    return 0 if result.error is None else 1


def create_cli_parser() -> argparse.ArgumentParser:
    """Request không chứa private path; store root do PRODUCT truyền theo Settings."""
    parser = argparse.ArgumentParser(description="EX-REC upload video preparation (REC-02 → REC-02A)")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """SIGTERM thành interrupt để FFmpeg subprocess được dọn qua context managers."""
    args = create_cli_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    previous = signal.getsignal(signal.SIGTERM)

    def interrupt(signum: int, frame: object) -> None:
        """Dừng có kiểm soát khi PRODUCT cancel job."""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        return _execute(args)
    except KeyboardInterrupt:
        print(json.dumps({"error_code": "PREPARE_INTERRUPTED"}))
        return 130
    except (ValueError, OSError, RuntimeError) as error:
        logger.error("Prepare setup/publication failed cause=%s", type(error).__name__)
        print(json.dumps({"error_code": "PREPARE_SETUP_OR_PUBLICATION_FAILED", "error_type": type(error).__name__}))
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
