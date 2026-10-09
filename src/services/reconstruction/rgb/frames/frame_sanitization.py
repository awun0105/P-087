"""Thay frame set vừa tách bằng bản đã che khuôn mặt/biển số (AUD-18, ADR 0019).

Chạy ngay sau REC-02A và trước mọi bước dùng frame (COLMAP, Brush, thumbnail, các view): stage
`ST-FRAME-EXTRACT` của job trỏ tới frame set đã che. Frame có vùng bị che được thay bằng bản mới ở
`rec02a/sanitized/`; frame không có vùng nào giữ nguyên artifact gốc, nên các bước sau không còn đường tới
bản gốc của bất kỳ frame nào đã bị che. Job chạy tiếp ngay, không chờ người duyệt (owner chốt 2026-10-09).
Bước này không cấp trạng thái "đã ẩn danh": privacy report của job giữ nguyên.
"""

import hashlib
import json
import logging
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.manifests import StageId
from src.models.contracts.sanitization import SanitizationManifest
from src.services.reconstruction.rgb.frames.frame_extraction import FrameExtractionError
from src.services.reconstruction.rgb.frames.frame_set import NormalizedRGBFrameSet, _sha256
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter
from src.services.reconstruction.rgb.preflight.sanitization import DEFAULT_CONFIG, manifest_from_runner_result

logger = logging.getLogger(__name__)
RUNNER = Path(__file__).resolve().parents[2] / "adapters" / "anonymize_runner.py"

#: Nhận (thư mục frame nguồn, thư mục đích chưa tồn tại, tên frame theo thứ tự) và trả kết quả của runner.
RunAnonymizer = Callable[[Path, Path, list[str]], dict[str, Any]]


def _failure(message: str, action: str) -> FrameExtractionError:
    return FrameExtractionError("FRAME_ANONYMIZATION_FAILED", message, action)


def subprocess_anonymizer(python: Path, weights_dir: Path, timeout_seconds: float = 3600.0) -> RunAnonymizer:
    """Runner thật: EgoBlur Gen2 trong `scene_runtime`. Mã thoát khác 0 hoặc thiếu kết quả đều là lỗi."""

    def run(frames_dir: Path, output_dir: Path, names: list[str]) -> dict[str, Any]:
        request_path, result_path = output_dir.parent / "anonymize.request.json", output_dir.parent / "anonymize.json"
        request = {
            "frames_dir": str(frames_dir),
            "output_dir": str(output_dir),
            "weights_dir": str(weights_dir),
            "frame_names": names,
            "config": {**DEFAULT_CONFIG, "device": "cuda:0"},
        }
        request_path.write_text(json.dumps(request), encoding="utf-8")
        try:
            completed = subprocess.run(  # noqa: S603 - argv cố định, không qua shell
                [str(python), str(RUNNER), "--request", str(request_path), "--result", str(result_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise _failure(
                "Face/plate anonymizer did not run", "Check the scene runtime and EgoBlur weights"
            ) from error
        if completed.returncode != 0 or not result_path.is_file():
            # Chỉ vào log của worker; thông báo trả về UI không kèm stderr hay đường dẫn.
            logger.error("Anonymizer exit=%s stderr=%s", completed.returncode, completed.stderr[-2000:])
            raise _failure("Face/plate anonymizer failed", "Check the scene runtime, GPU memory and EgoBlur weights")
        return json.loads(result_path.read_text(encoding="utf-8"))

    return run


@dataclass(frozen=True)
class FrameSanitizer:
    """Che mọi frame của một frame set và publish bản đã che cùng SanitizationManifest."""

    writer: ArtifactWriter
    require: Callable[[ProductArtifactRef], Path]
    run: RunAnonymizer

    def sanitize(
        self, job_id: str, frame_set: NormalizedRGBFrameSet
    ) -> tuple[ProductArtifactRef, NormalizedRGBFrameSet, SanitizationManifest]:
        """Trả (ref frame set đã che, frame set đã che, manifest). Thiếu một frame là lỗi cả bước."""
        try:
            return self._sanitize(job_id, frame_set)
        except FrameExtractionError:
            raise
        except Exception as error:
            # Storage được inject có exception type riêng của owner khác (vd. bytes cũ khác khi retry); mọi lỗi ở
            # đây đều phải thành lỗi của bước che, không được để job chạy tiếp trên frame gốc.
            raise _failure(
                "Face/plate anonymization output is incomplete or inconsistent",
                "Rerun preparation; do not train on the unredacted frames",
            ) from error

    def _sanitize(
        self, job_id: str, frame_set: NormalizedRGBFrameSet
    ) -> tuple[ProductArtifactRef, NormalizedRGBFrameSet, SanitizationManifest]:
        with tempfile.TemporaryDirectory(prefix="rec02a_sanitize_") as directory:
            source, target = Path(directory) / "in", Path(directory) / "out"
            source.mkdir()
            names: list[str] = []
            for frame in frame_set.frames:
                path = self.require(frame.image)
                if _sha256(path) != frame.image.artifact_checksum:
                    raise ValueError(f"frame bytes changed before anonymization: {frame.frame_id}")
                name = f"{frame.frame_id:06d}{path.suffix.lower() or '.png'}"
                (source / name).symlink_to(path.resolve())
                names.append(name)
            manifest = manifest_from_runner_result(self.run(source, target, names), frame_set.frame_set_checksum)
            if not manifest.complete:
                raise _failure(
                    f"Face/plate anonymization failed on {len(manifest.failures)} frame(s)",
                    "Rerun preparation; do not train on the unredacted frames",
                )
            by_name = {frame.frame_name: frame for frame in manifest.frames}
            if list(by_name) != names:
                raise ValueError("anonymizer returned a different frame inventory")
            frames = []
            for frame, name in zip(frame_set.frames, names, strict=True):
                record = by_name[name]
                if record.source_checksum != frame.image.artifact_checksum:
                    raise ValueError(f"anonymizer read different source bytes: {frame.frame_id}")
                if not record.regions:
                    # Không có vùng nào bị che: manifest đã buộc byte giống hệt bản gốc, nên dùng luôn artifact gốc
                    # thay vì đọc, băm và publish lại một bản sao (phần lớn frame rơi vào trường hợp này).
                    frames.append(frame)
                    continue
                payload = (target / name).read_bytes()
                reference = self._publish(job_id, f"frames/{name}", "RGBFrame", payload)
                if reference.artifact_checksum != record.sanitized_checksum:
                    raise ValueError(f"sanitized frame bytes differ from the manifest: {frame.frame_id}")
                frames.append(frame.model_copy(update={"image": reference}))
        self._publish(
            job_id, "manifest.json", "SanitizationManifest", manifest.model_dump_json(indent=2).encode() + b"\n"
        )
        draft = frame_set.model_dump(mode="json")
        draft["frames"] = [frame.model_dump(mode="json") for frame in frames]
        draft["sanitization_manifest_checksum"] = manifest.manifest_checksum
        draft["frame_set_checksum"] = canonical_content_checksum(draft, "frame_set_checksum")
        sanitized = NormalizedRGBFrameSet.model_validate(draft)
        reference = self._publish(
            job_id, "frame_set.json", "NormalizedRGBFrameSet", sanitized.model_dump_json(indent=2).encode() + b"\n"
        )
        return reference, sanitized, manifest

    def _publish(self, job_id: str, path: str, kind: str, payload: bytes) -> ProductArtifactRef:
        reference = ProductArtifactRef(
            artifact_type=kind,
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{job_id}/rec02a/sanitized/{path}",
            artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.FRAME_EXTRACT,
            job_id=job_id,
        )
        return ProductArtifactRef.model_validate(self.writer.publish(reference, payload).model_dump())
