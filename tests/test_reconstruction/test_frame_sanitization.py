"""AUD-18: bước che khuôn mặt/biển số thay frame set của job; lỗi thì không lùi về frame gốc."""

import dataclasses
import hashlib
from pathlib import Path
from typing import Any

from src.models.contracts.manifests import StageId
from src.models.contracts.sanitization import SanitizationManifest
from src.services.reconstruction.prepare_cli import VideoInputPreparer
from src.services.reconstruction.prepare_models import PrepareInputRequest
from src.services.reconstruction.rgb.frames.frame_sanitization import FrameSanitizer
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver
from src.services.reconstruction.rgb.preflight.sanitization import DEFAULT_CONFIG
from tests.test_reconstruction.test_rec_prepare_input import _ATTESTED, _preparer, _profile, _publish_input, _video

JOB = "job-prepare-0001"
REDACTED = b"redacted-frame-bytes"


def _checksum(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _fake_anonymizer(*, fail: str | None = None, lie_about: str | None = None, calls: list | None = None):  # noqa: ANN202
    """Che frame đầu (ghi byte khác), chép nguyên các frame còn lại; giống định dạng kết quả của runner thật."""

    def run(source: Path, target: Path, names: list[str]) -> dict[str, Any]:
        if calls is not None:
            calls.append(names)
        target.mkdir()
        frames, failures = [], []
        for index, name in enumerate(names):
            if name == fail:
                failures.append(name)
                continue
            original = (source / name).read_bytes()
            regions = []
            if index == 0:
                (target / name).write_bytes(REDACTED)
                regions = [
                    {
                        "kind": "face",
                        "box": [2, 2, 10, 10],
                        "applied_box": [1, 1, 12, 12],
                        "score": 0.9,
                        "origin": "detected",
                    }
                ]
            recorded = (target / name).read_bytes() if regions else original
            frames.append(
                {
                    "frame_name": name,
                    "width": 32,
                    "height": 24,
                    "source_checksum": _checksum(original),
                    "sanitized_checksum": _checksum(b"something else" if name == lie_about else recorded),
                    "regions": regions,
                }
            )
        return {
            "detector": {
                "name": "egoblur-gen2",
                "package_version": "2.0.1",
                "torch_version": "2.7.1+cu126",
                "torchvision_version": "0.22.1+cu126",
                "face_weights_checksum": _checksum(b"face"),
                "plate_weights_checksum": _checksum(b"plate"),
            },
            "config": DEFAULT_CONFIG,
            "requested_frame_count": len(names),
            "frames": frames,
            "failures": failures,
        }

    return run


def _setup(tmp_path: Path, anonymizer=None):  # noqa: ANN001, ANN202
    preparer, resolver, store = _preparer(tmp_path)
    if anonymizer is not None:
        sanitizer = FrameSanitizer(preparer.deps.writer, resolver.require, anonymizer)
        preparer = VideoInputPreparer(dataclasses.replace(preparer.deps, sanitizer=sanitizer))
    manifest_ref = _publish_input(store, _video(tmp_path, "testsrc2=duration=2:size=32x24:rate=6"), _ATTESTED)
    request = PrepareInputRequest(
        job_id=JOB,
        input_manifest_ref=manifest_ref,
        quality_profile=_profile(),
        sample_fps=2,
        max_frames=50,
        anonymize=True,
    )
    return preparer, resolver, request


def test_anonymize_replaces_the_job_frame_set_with_the_redacted_copy(tmp_path: Path) -> None:
    calls: list = []
    preparer, resolver, request = _setup(tmp_path, _fake_anonymizer(calls=calls))
    raw = preparer.run(request.model_copy(update={"anonymize": False}))
    result = preparer.run(request)

    assert result.error is None and result.frame_set_ref is not None and raw.frame_set_ref is not None
    assert result.frame_set_ref != raw.frame_set_ref
    assert "/rec02a/sanitized/frame_set.json" in result.frame_set_ref.artifact_uri
    stage = next(stage for stage in result.stage_artifacts if stage.stage_id == StageId.FRAME_EXTRACT)
    assert (stage.artifact_uri, stage.artifact_checksum) == (
        result.frame_set_ref.artifact_uri,
        result.frame_set_ref.artifact_checksum,
    )
    loader = FrameSetResolver(resolver.require, resolver.require)
    original, sanitized = loader.load(raw.frame_set_ref), loader.load(result.frame_set_ref)
    assert [f.frame_id for f in sanitized.frames] == [f.frame_id for f in original.frames]
    assert [f.timestamp_sec for f in sanitized.frames] == [f.timestamp_sec for f in original.frames]
    assert original.sanitization_manifest_checksum is None and sanitized.sanitization_manifest_checksum is not None
    assert sanitized.frame_set_checksum != original.frame_set_checksum
    # Frame bị che được thay bằng bản mới; frame không bị che dùng lại đúng artifact gốc, không publish bản sao.
    assert "/rec02a/sanitized/frames/" in sanitized.frames[0].image.artifact_uri
    assert sanitized.frames[0].image != original.frames[0].image
    assert [f.image for f in sanitized.frames[1:]] == [f.image for f in original.frames[1:]]
    copies = resolver.artifact_root / "jobs" / JOB / "rec02a" / "sanitized" / "frames"
    assert sorted(path.name for path in copies.iterdir()) == [f"{original.frames[0].frame_id:06d}.png"]
    paths = loader.materialize(sanitized)
    assert paths[0][1].read_bytes() == REDACTED
    assert paths[1][1].read_bytes() == resolver.require(original.frames[1].image).read_bytes()
    assert calls == [[f"{frame.frame_id:06d}.png" for frame in original.frames]]

    manifest_path = resolver.resolve(result.frame_set_ref.artifact_uri.replace("frame_set.json", "manifest.json"))
    manifest = SanitizationManifest.model_validate_json(manifest_path.read_text())
    assert manifest.complete and manifest.manifest_checksum == sanitized.sanitization_manifest_checksum
    assert manifest.source_frame_set_checksum == original.frame_set_checksum
    assert [len(frame.regions) for frame in manifest.frames] == [1, 0, 0, 0]
    # Retry cùng job cho ra đúng artifact cũ.
    assert preparer.run(request).frame_set_ref == result.frame_set_ref


def test_anonymize_without_a_configured_anonymizer_fails_closed(tmp_path: Path) -> None:
    preparer, _, request = _setup(tmp_path)
    result = preparer.run(request)

    assert result.frame_set_ref is None and result.error is not None
    assert result.error.error_code == "FRAME_ANONYMIZER_UNAVAILABLE" and result.error.stage_id == StageId.FRAME_EXTRACT
    assert not result.error.retryable
    assert [s.status for s in result.stage_artifacts if s.stage_id == StageId.FRAME_EXTRACT] == ["FAILED"]


def test_a_failed_frame_or_inconsistent_output_never_falls_back_to_raw_frames(tmp_path: Path) -> None:
    for index, anonymizer in enumerate(
        (_fake_anonymizer(fail="000003.png"), _fake_anonymizer(lie_about="000003.png"), lambda *_: {"frames": []})
    ):
        root = tmp_path / str(index)
        root.mkdir()
        preparer, resolver, request = _setup(root, anonymizer)
        # Dùng đúng tên frame thứ hai của video này để lỗi rơi vào một frame có thật.
        raw = preparer.run(request.model_copy(update={"anonymize": False}))
        second = FrameSetResolver(resolver.require, resolver.require).load(raw.frame_set_ref).frames[1].frame_id
        if index < 2:
            key = "fail" if index == 0 else "lie_about"
            sanitizer = FrameSanitizer(
                preparer.deps.writer, resolver.require, _fake_anonymizer(**{key: f"{second:06d}.png"})
            )
            preparer = VideoInputPreparer(dataclasses.replace(preparer.deps, sanitizer=sanitizer))
        result = preparer.run(request)

        assert result.frame_set_ref is None and result.error is not None, index
        assert result.error.error_code == "FRAME_ANONYMIZATION_FAILED", index
        assert not (resolver.artifact_root / "jobs" / JOB / "rec02a" / "sanitized" / "frame_set.json").exists(), index
        succeeded = [
            s for s in result.stage_artifacts if s.stage_id == StageId.FRAME_EXTRACT and s.status == "SUCCEEDED"
        ]
        assert succeeded == [], index


def test_default_request_does_not_touch_the_anonymizer(tmp_path: Path) -> None:
    calls: list = []
    preparer, _, request = _setup(tmp_path, _fake_anonymizer(calls=calls))
    result = preparer.run(request.model_copy(update={"anonymize": False}))

    assert result.error is None and result.frame_set_ref is not None and calls == []
    assert "/rec02a/frame_set.json" in result.frame_set_ref.artifact_uri
    assert PrepareInputRequest.model_fields["anonymize"].default is False
