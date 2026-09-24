"""REC-02 quality/privacy invariants and a small real FFmpeg decoder smoke."""

import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from scripts.torwic.rec02_quality import publish_report
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import InputManifest, PrivacyInspectionScope, PrivacyResult
from src.services.orchestration.artifacts.store import ArtifactResolver, FilesystemArtifactStore
from src.services.reconstruction.rgb.ffmpeg_probe import FFmpegProbeError, FFmpegRGBProbe
from src.services.reconstruction.rgb.manifest_frames import RGBManifestFrameAdapter, RGBManifestFrameSelection
from src.services.reconstruction.rgb.privacy import (
    PrivacyDispatchProof,
    PrivacyInspectionEvidence,
    PrivacyQAAcceptance,
    PrivacyReviewRequest,
    RGBPrivacyGate,
)
from src.services.reconstruction.rgb.publication import RGBPreflightPublisher, VerifiedPrivacyPublication
from src.services.reconstruction.rgb.quality import (
    RGBQualityRequest,
    RGBQualityValidator,
    RGBValidationError,
    RGBVideoRequest,
)
from src.services.reconstruction.rgb.quality_models import RGBFrameAsset, RGBQualityProfile, RGBQualityReport

ROOT = Path(__file__).parents[2]


def _profile(**changes: object) -> RGBQualityProfile:
    """Build a checksum-valid task-local policy for isolated tests."""
    payload = json.loads((ROOT / "configs/torwic/aisle_cw_rec02_quality_v1.json").read_text())
    payload.update(changes)
    payload["profile_checksum"] = canonical_content_checksum(payload, "profile_checksum")
    return RGBQualityProfile.model_validate(payload)


def _assets(root: Path, payloads: tuple[bytes, ...]) -> tuple[RGBFrameAsset, ...]:
    """Create checksummed frame refs with no dataset dependency."""
    assets = []
    for index, payload in enumerate(payloads):
        path = root / f"{index:06d}.png"
        path.write_bytes(payload)
        assets.append(RGBFrameAsset(index, path, "sha256:" + hashlib.sha256(payload).hexdigest()))
    return tuple(assets)


def _request(frames: tuple[RGBFrameAsset, ...], profile: RGBQualityProfile) -> RGBQualityRequest:
    """Bind frame analysis to explicit source and selection identities."""
    checksum = "sha256:" + "a" * 64
    return RGBQualityRequest(frames, checksum, checksum, profile)


class _FakeProbe(FFmpegRGBProbe):
    """Deterministic metric seam; real decoder is tested separately."""

    def __init__(self, blur: list[float], motion: list[float | None]) -> None:
        self.blur = blur
        self.motion = motion

    def blur_scores(self, frames: tuple[RGBFrameAsset, ...], profile: RGBQualityProfile) -> list[float]:
        return self.blur

    def motion_scores(self, frames: tuple[RGBFrameAsset, ...], profile: RGBQualityProfile) -> list[float | None]:
        return self.motion

    def version(self) -> str:
        return "ffmpeg-test"


def _manifest() -> InputManifest:
    """Load shared contract fixture rather than inventing a privacy schema."""
    path = ROOT / "fixtures/mock_job/input_manifest.json"
    return InputManifest.model_validate_json(path.read_text())


def _video_manifest(video: Path) -> InputManifest:
    """Bind one synthetic video to a shared InputManifest fixture shape."""
    payload = _manifest().model_dump(mode="json")
    payload["files"] = [
        {
            "original_name": video.name,
            "media_type": "video/mp4",
            "size_bytes": video.stat().st_size,
            "checksum": "sha256:" + hashlib.sha256(video.read_bytes()).hexdigest(),
            "artifact_uri": "artifact://jobs/rec02-test/input/input.mp4",
            "data_class": "product_input",
        }
    ]
    payload["input_manifest_checksum"] = canonical_content_checksum(payload, "input_manifest_checksum")
    return InputManifest.model_validate(payload)


def _inspection(count: int, scope: PrivacyInspectionScope) -> PrivacyInspectionEvidence:
    """Explicit human/tool inspection facts with a stable evidence identity."""
    evidence = PrivacyInspectionEvidence(scope, 3, count, (), "sha256:" + "0" * 64)
    return PrivacyInspectionEvidence(
        scope, 3, count, (), canonical_content_checksum(asdict(evidence), "evidence_checksum")
    )


def test_profile_identity_and_wrong_checksum() -> None:
    """Edited thresholds cannot masquerade as the approved profile."""
    profile = _profile()
    assert profile.blur_exclude_gt == 8.5
    with pytest.raises(ValueError, match="checksum"):
        RGBQualityProfile.model_validate({**profile.model_dump(), "blur_exclude_gt": 9.5})


def test_blur_mask_is_logical_and_motion_is_only_warning(tmp_path: Path) -> None:
    """Quality rejection leaves source bytes and frozen selection untouched."""
    frames = _assets(tmp_path, (b"one", b"two", b"three", b"four"))
    request = _request(frames, _profile(warn_active_ratio_lt=0.7, warn_static_run_gt=0))
    report = RGBQualityValidator(_FakeProbe([5, 9, 5, 5], [None, 0, 5])).validate(request)
    assert report.selected_frame_ids == [0, 1, 2, 3]
    assert report.excluded_frame_ids == [1]
    assert report.effective_reconstruction_frame_ids == [0, 2, 3]
    assert report.motion.observed_transition_count == 1
    assert report.motion.active_ratio == 1.0
    assert all(frame.path.read_bytes() for frame in frames)
    verify_content_checksum(report, "report_checksum")


def test_low_motion_reports_warning_without_rejecting_frames(tmp_path: Path) -> None:
    """A 69%-style heuristic cannot become a hidden hard acceptance gate."""
    frames = _assets(tmp_path, (b"one", b"two", b"three"))
    report = RGBQualityValidator(_FakeProbe([5, 5, 5], [None, 0, 0])).validate(_request(frames, _profile()))
    assert report.effective_reconstruction_frame_ids == [0, 1, 2]
    assert report.motion.warnings == ["ACTIVE_RATIO_BELOW_REFERENCE"]
    assert report.motion.registration_feasibility == "NOT_ESTABLISHED_PRE_COLMAP"


def test_motion_probe_failure_is_diagnostic_only(tmp_path: Path) -> None:
    """A missing motion estimate cannot turn a quality warning into input FAIL."""

    class FailedMotionProbe(_FakeProbe):
        def motion_scores(self, frames: tuple[RGBFrameAsset, ...], profile: RGBQualityProfile) -> list[float | None]:
            raise FFmpegProbeError("feature estimate unavailable")

    frames = _assets(tmp_path, (b"one", b"two", b"three"))
    report = RGBQualityValidator(FailedMotionProbe([5, 5, 5], [])).validate(_request(frames, _profile()))
    assert report.effective_reconstruction_frame_ids == [0, 1, 2]
    assert "MOTION_PROBE_FAILED" in report.motion.warnings
    assert report.motion.active_ratio is None


def test_source_checksum_and_duplicate_ids_fail_before_probe(tmp_path: Path) -> None:
    """Source identity and sequence structure are true hard gates."""
    frames = _assets(tmp_path, (b"one", b"two"))
    bad = (frames[0], RGBFrameAsset(0, frames[1].path, frames[1].checksum))
    validator = RGBQualityValidator(_FakeProbe([5, 5], [None, 1]))
    with pytest.raises(RGBValidationError, match="unique and ordered"):
        validator.validate(_request(bad, _profile()))
    frames[1].path.write_bytes(b"changed")
    with pytest.raises(RGBValidationError, match="checksum changed"):
        validator.validate(_request(frames, _profile()))


def test_identical_sequence_rejected_as_static(tmp_path: Path) -> None:
    """Byte-identical sequence is a defensible structural static failure."""
    frames = _assets(tmp_path, (b"same", b"same"))
    with pytest.raises(RGBValidationError) as error:
        RGBQualityValidator(_FakeProbe([5, 5], [None, 0])).validate(_request(frames, _profile()))
    assert error.value.to_execution_error().error_code == "RGB_STATIC_SEQUENCE"


def test_privacy_sample_and_findings_fail_dispatch() -> None:
    """Sampled screening and unresolved findings never authorize reconstruction."""
    manifest = _manifest()
    gate = RGBPrivacyGate()
    sample = gate.evaluate(PrivacyReviewRequest(manifest, _inspection(1, PrivacyInspectionScope.SAMPLED)))
    assert sample.result == PrivacyResult.PRELIMINARY_SCREENED
    acceptance = PrivacyQAAcceptance(manifest.input_manifest_checksum, "sha256:" + "b" * 64, "qa-1")
    with pytest.raises(RGBValidationError, match="not privacy-cleared"):
        gate.require_dispatch(
            manifest, PrivacyDispatchProof(sample, _inspection(1, PrivacyInspectionScope.SAMPLED), acceptance)
        )
    finding = PrivacyInspectionEvidence(
        PrivacyInspectionScope.ALL_SELECTED_FRAMES, 3, 3, ({"kind": "unresolved_pii"},), "sha256:" + "0" * 64
    )
    finding = PrivacyInspectionEvidence(
        finding.scope,
        3,
        3,
        finding.unresolved_findings,
        canonical_content_checksum(asdict(finding), "evidence_checksum"),
    )
    assert gate.evaluate(PrivacyReviewRequest(manifest, finding)).result == PrivacyResult.QUARANTINED


def test_privacy_requires_exact_qa_acceptance_and_input_binding() -> None:
    """Verified state needs full inspection, QA and exact InputManifest identity."""
    manifest = _manifest()
    evidence = _inspection(3, PrivacyInspectionScope.ALL_SELECTED_FRAMES)
    gate = RGBPrivacyGate(lambda approval: approval.acceptance_reference == "qa-1")
    assert (
        RGBPrivacyGate().evaluate(PrivacyReviewRequest(manifest, evidence)).result == PrivacyResult.PRELIMINARY_SCREENED
    )
    assert gate.evaluate(PrivacyReviewRequest(manifest, evidence)).result == PrivacyResult.PRELIMINARY_SCREENED
    wrong = PrivacyQAAcceptance("sha256:" + "c" * 64, evidence.evidence_checksum, "qa-1")
    assert gate.evaluate(PrivacyReviewRequest(manifest, evidence, wrong)).result == PrivacyResult.PRELIMINARY_SCREENED
    approval = PrivacyQAAcceptance(manifest.input_manifest_checksum, evidence.evidence_checksum, "qa-1")
    assert (
        RGBPrivacyGate().evaluate(PrivacyReviewRequest(manifest, evidence, approval)).result
        == PrivacyResult.PRELIMINARY_SCREENED
    )
    verified = gate.evaluate(PrivacyReviewRequest(manifest, evidence, approval))
    assert verified.result == PrivacyResult.VERIFIED_ANONYMIZED
    gate.require_dispatch(manifest, PrivacyDispatchProof(verified, evidence, approval))
    with pytest.raises(RGBValidationError, match="not privacy-cleared"):
        RGBPrivacyGate().require_dispatch(manifest, PrivacyDispatchProof(verified, evidence, approval))
    changed = verified.model_copy(update={"input_manifest_checksum": "sha256:" + "d" * 64})
    with pytest.raises(ValueError, match="report_checksum"):
        gate.require_dispatch(manifest, PrivacyDispatchProof(changed, evidence, approval))


def test_privacy_zero_inspection_and_forged_evidence_fail() -> None:
    """Zero inspected frames cannot be labeled screened; evidence is checksummed."""
    manifest = _manifest()
    gate = RGBPrivacyGate()
    with pytest.raises(RGBValidationError, match="counts are invalid"):
        gate.evaluate(PrivacyReviewRequest(manifest, _inspection(0, PrivacyInspectionScope.SAMPLED)))
    evidence = _inspection(1, PrivacyInspectionScope.SAMPLED)
    forged = PrivacyInspectionEvidence(
        evidence.scope,
        evidence.selected_frame_count,
        evidence.inspected_frame_count,
        ({"kind": "new"},),
        evidence.evidence_checksum,
    )
    with pytest.raises(RGBValidationError, match="evidence changed"):
        gate.evaluate(PrivacyReviewRequest(manifest, forged))
    with pytest.raises(RGBValidationError, match="no checksum"):
        gate.evaluate(PrivacyReviewRequest(manifest, _inspection(1, PrivacyInspectionScope.APPROVED_COPY)))


def test_privacy_requires_source_rights_attestation() -> None:
    """A valid checksum cannot replace the product rights decision."""
    payload = _manifest().model_dump(mode="json")
    payload["source_rights_attestation"] = {"attested": False}
    payload["input_manifest_checksum"] = canonical_content_checksum(payload, "input_manifest_checksum")
    manifest = InputManifest.model_validate(payload)
    with pytest.raises(RGBValidationError, match="not attested"):
        RGBPrivacyGate().evaluate(PrivacyReviewRequest(manifest, _inspection(1, PrivacyInspectionScope.SAMPLED)))


def test_quality_report_detects_mask_tampering(tmp_path: Path) -> None:
    """Recomputed checksum alone cannot excuse inconsistent effective IDs."""
    frames = _assets(tmp_path, (b"one", b"two", b"three"))
    report = RGBQualityValidator(_FakeProbe([5, 9, 5], [None, None])).validate(_request(frames, _profile()))
    altered = report.model_dump(mode="json")
    altered["effective_reconstruction_frame_ids"] = [0, 1]
    altered["report_checksum"] = canonical_content_checksum(altered, "report_checksum")
    with pytest.raises(ValueError, match="quality mask"):
        RGBQualityReport.model_validate(altered)
    altered = report.model_dump(mode="json")
    altered["frames"][1]["reasons"] = []
    altered["report_checksum"] = canonical_content_checksum(altered, "report_checksum")
    with pytest.raises(ValueError, match="reason does not match"):
        RGBQualityReport.model_validate(altered)


def test_offline_report_publication_is_immutable(tmp_path: Path) -> None:
    """A repeated identical analysis is safe; changed evidence cannot overwrite."""
    frames = _assets(tmp_path, (b"one", b"two", b"three"))
    validator = RGBQualityValidator(_FakeProbe([5, 5, 5], [None, 2, 2]))
    request = _request(frames, _profile())
    first = validator.validate(request)
    output = tmp_path / "quality_report.json"
    publish_report(output, first)
    before = output.read_bytes()
    publish_report(output, first)
    assert output.read_bytes() == before
    changed = RGBQualityValidator(_FakeProbe([5, 5, 6], [None, 2, 2])).validate(request)
    with pytest.raises(ValueError, match="differs"):
        publish_report(output, changed)
    assert output.read_bytes() == before


def test_published_quality_and_privacy_refs_resolve(tmp_path: Path) -> None:
    """Real artifact store resolves both report types without file renaming."""
    frames = _assets(tmp_path, (b"one", b"two", b"three"))
    quality = RGBQualityValidator(_FakeProbe([5, 5, 5], [None, 2, 2])).validate(_request(frames, _profile()))
    manifest = _manifest()
    privacy = RGBPrivacyGate().evaluate(PrivacyReviewRequest(manifest, _inspection(1, PrivacyInspectionScope.SAMPLED)))
    resolver = ArtifactResolver(tmp_path / "artifacts")
    publisher = RGBPreflightPublisher(FilesystemArtifactStore(resolver))
    quality_ref = publisher.publish_quality(quality, "rec02-test")
    privacy_ref = publisher.publish_privacy(privacy, "rec02-test")
    assert resolver.load_model(quality_ref, RGBQualityReport).report_checksum == quality.report_checksum
    assert resolver.load_model(privacy_ref, type(privacy)).report_checksum == privacy.report_checksum
    assert quality_ref.source_provenance["profile_checksum"] == _profile().profile_checksum
    assert quality_ref.artifact_checksum != quality.report_checksum


def test_verified_privacy_cannot_bypass_qa_at_publication(tmp_path: Path) -> None:
    """A checksummed VERIFIED report alone cannot be published as cleared."""
    manifest = _manifest()
    evidence = _inspection(3, PrivacyInspectionScope.ALL_SELECTED_FRAMES)
    approval = PrivacyQAAcceptance(manifest.input_manifest_checksum, evidence.evidence_checksum, "qa-fixture")
    gate = RGBPrivacyGate(lambda item: item.acceptance_reference == "qa-fixture")
    report = gate.evaluate(PrivacyReviewRequest(manifest, evidence, approval))
    proof = PrivacyDispatchProof(report, evidence, approval)
    resolver = ArtifactResolver(tmp_path / "artifacts")
    writer = FilesystemArtifactStore(resolver)
    with pytest.raises(ValueError, match="requires QA dispatch proof"):
        RGBPreflightPublisher(writer).publish_privacy(report, "rec02-test")
    with pytest.raises(ValueError, match="QA verifier is unavailable"):
        RGBPreflightPublisher(writer).publish_verified_privacy(
            VerifiedPrivacyPublication(manifest, proof, "rec02-test")
        )
    ref = RGBPreflightPublisher(writer, gate).publish_verified_privacy(
        VerifiedPrivacyPublication(manifest, proof, "rec02-test")
    )
    assert resolver.load_model(ref, type(report)).result == PrivacyResult.VERIFIED_ANONYMIZED


def test_input_manifest_adapter_resolves_only_selected_rgb(tmp_path: Path) -> None:
    """Shared input refs bind bytes, size and explicit reconstruction selection."""
    frames = _assets(tmp_path, (b"one", b"two", b"three"))
    payload = _manifest().model_dump(mode="json")
    payload["files"] = [
        {
            "original_name": frame.path.name,
            "media_type": "image/png",
            "size_bytes": frame.path.stat().st_size,
            "checksum": frame.checksum,
            "artifact_uri": f"artifact://jobs/rec02-test/input/{frame.path.name}",
            "data_class": "product_input",
        }
        for frame in frames
    ]
    payload["input_manifest_checksum"] = canonical_content_checksum(payload, "input_manifest_checksum")
    manifest = InputManifest.model_validate(payload)
    mapping = {item.artifact_uri: frame.path for item, frame in zip(manifest.files, frames, strict=True)}
    adapter = RGBManifestFrameAdapter(mapping.__getitem__)
    selection = RGBManifestFrameSelection(manifest, (0, 1, 2), "sha256:" + "c" * 64, _profile())
    report = RGBQualityValidator(_FakeProbe([5, 9, 5], [None, None])).validate(adapter.build_request(selection))
    assert report.source_manifest_checksum == manifest.input_manifest_checksum
    assert report.effective_reconstruction_frame_ids == [0, 2]
    with pytest.raises(RGBValidationError, match="selection differs"):
        adapter.build_request(
            RGBManifestFrameSelection(manifest, (0, 1), selection.selection_checksum, selection.profile)
        )


def test_real_ffmpeg_decodes_synthetic_png_sequence(tmp_path: Path) -> None:
    """A real FFmpeg pass proves decoder/filter command execution on PNGs."""
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=10",
        "-frames:v",
        "3",
        str(tmp_path / "%06d.png"),
    ]
    subprocess.run(command, check=True, capture_output=True)
    paths = sorted(tmp_path.glob("*.png"))
    frames = tuple(
        RGBFrameAsset(i, path, "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())
        for i, path in enumerate(paths)
    )
    profile = _profile(blur_exclude_gt=None)
    report = RGBQualityValidator(FFmpegRGBProbe()).validate(_request(frames, profile))
    assert len(report.frames) == 3
    assert report.effective_reconstruction_frame_ids == [0, 1, 2]


def test_real_ffmpeg_video_preflight_from_input_manifest(tmp_path: Path) -> None:
    """The product video profile decodes real bytes without a TorWIC adapter."""
    video = tmp_path / "input.mp4"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=10:duration=0.4",
        "-c:v",
        "mpeg4",
        str(video),
    ]
    subprocess.run(command, check=True, capture_output=True)
    manifest = _video_manifest(video)
    adapter = RGBManifestFrameAdapter(lambda uri: video)
    request = adapter.build_video_request(manifest, _profile(blur_exclude_gt=None))
    report = RGBQualityValidator(FFmpegRGBProbe()).validate_video(request)
    assert report.selected_frame_ids == [0, 1, 2, 3]
    assert report.effective_reconstruction_frame_ids == [0, 1, 2, 3]
    assert report.motion.registration_feasibility == "NOT_ESTABLISHED_PRE_COLMAP"


def test_exact_static_video_is_structurally_rejected(tmp_path: Path) -> None:
    """Exact decoded-frame identity is stronger than a soft motion proxy."""
    video = tmp_path / "input.mp4"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=320x180:r=10:d=0.4",
        "-c:v",
        "mpeg4",
        str(video),
    ]
    subprocess.run(command, check=True, capture_output=True)
    manifest = _video_manifest(video)
    adapter = RGBManifestFrameAdapter(lambda uri: video)
    request = adapter.build_video_request(manifest, _profile(blur_exclude_gt=None))
    with pytest.raises(RGBValidationError) as error:
        RGBQualityValidator(FFmpegRGBProbe()).validate_video(request)
    assert error.value.code == "RGB_STATIC_SEQUENCE"


def test_corrupt_video_fails_structural_gate(tmp_path: Path) -> None:
    """An intact checksum cannot make undecodable video valid."""
    video = tmp_path / "bad.mp4"
    video.write_bytes(b"not a video")
    request = RGBVideoRequest(
        video,
        "sha256:" + hashlib.sha256(video.read_bytes()).hexdigest(),
        video.stat().st_size,
        "sha256:" + "a" * 64,
        _profile(blur_exclude_gt=None),
    )
    with pytest.raises(RGBValidationError) as error:
        RGBQualityValidator(FFmpegRGBProbe()).validate_video(request)
    assert error.value.code == "RGB_DECODE_FAILED"


def test_corrupt_png_fails_structural_gate(tmp_path: Path) -> None:
    """A checksummed invalid PNG is still rejected before heavy stages."""
    frames = _assets(tmp_path, (b"not png 1", b"not png 2"))
    with pytest.raises(RGBValidationError) as error:
        RGBQualityValidator(FFmpegRGBProbe()).validate(_request(frames, _profile()))
    assert error.value.code == "RGB_DECODE_FAILED"
