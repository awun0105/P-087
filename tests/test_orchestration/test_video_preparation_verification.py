"""Server-side prepared-media identity and frame-map verification."""

import hashlib
import json
from pathlib import Path

import pytest

from src.models.contracts.identity import canonical_content_checksum
from src.models.contracts.video_preparation import (
    ClientVideoPreparationManifest,
    ServerVideoPreparationVerification,
    VideoStreamMetadata,
)
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.uploads.models import UploadRecord
from src.services.orchestration.uploads.video_preparation import (
    ServerVideoPreparationVerifier,
    VideoPreparationVerificationError,
)

ROOT = Path(__file__).parents[2]


def _sha(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _prepared_input(tmp_path: Path, *, pts: tuple[int, ...] = (0, 200, 400)):
    fixture = json.loads((ROOT / "fixtures/contracts/video_preparation_v1.json").read_text())
    prepared_bytes = b"server-observed prepared mp4 fixture"
    rows = fixture["frame_map_rows"]
    for row, output_pts in zip(rows, pts, strict=True):
        row["output_pts"] = output_pts
    sidecar = b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows)
    manifest_payload = fixture["preparation_manifest"]
    manifest_payload["prepared_file"].update(size_bytes=len(prepared_bytes), checksum=_sha(prepared_bytes))
    manifest_payload["frame_map"].update(size_bytes=len(sidecar), checksum=_sha(sidecar))
    manifest_payload["preparation_checksum"] = "sha256:" + "0" * 64
    manifest_payload["preparation_checksum"] = canonical_content_checksum(manifest_payload, "preparation_checksum")
    manifest = ClientVideoPreparationManifest.model_validate(manifest_payload)

    upload_id = "upload-video-map-test"
    artifact_uri = f"artifact://jobs/{upload_id}/input/source.mp4"
    resolver = ArtifactResolver(tmp_path / "artifacts")
    video_path = resolver.resolve(artifact_uri)
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(prepared_bytes)
    frame_map_path = tmp_path / "video_frame_map.jsonl"
    frame_map_path.write_bytes(sidecar)
    upload = UploadRecord(
        upload_id=upload_id,
        original_name="capture.prepared.mp4",
        media_type="video/mp4",
        size_bytes=len(prepared_bytes),
        checksum=_sha(prepared_bytes),
        artifact_uri=artifact_uri,
        received_at="2026-10-08T00:00:00Z",
        input_kind="rgb_video",
    )
    observed = manifest.prepared_video.model_copy(update={"codec": "h264"})
    return resolver, upload, manifest, frame_map_path, observed, pts


class FixtureVideoVerifier(ServerVideoPreparationVerifier):
    def __init__(self, resolver: ArtifactResolver, observed: VideoStreamMetadata, pts: tuple[int, ...]) -> None:
        super().__init__(resolver)
        self.observed = observed
        self.pts = pts

    def _probe(self, video: Path) -> VideoStreamMetadata:
        assert video.is_file()
        return self.observed

    def _presentation_pts(self, video: Path):
        assert video.is_file()
        return iter(self.pts)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("tv", "limited"), ("mpeg", "limited"), ("pc", "full"), ("jpeg", "full"), ("unknown", None), (None, None)],
)
def test_ffprobe_color_range_uses_contract_values(raw: str | None, expected: str | None) -> None:
    assert ServerVideoPreparationVerifier._color_range_value(raw) == expected


def test_server_verifies_actual_video_and_output_pts_then_publishes_map(tmp_path: Path) -> None:
    resolver, upload, manifest, sidecar, observed, pts = _prepared_input(tmp_path)
    verification = FixtureVideoVerifier(resolver, observed, pts).verify_and_publish(upload, manifest, sidecar)

    assert verification.status == "server_verified"
    assert verification.uploaded_checksum == upload.checksum
    assert verification.frame_map_ref.artifact_checksum == manifest.frame_map.checksum
    assert verification.original_source_status == "client_declared_unverified"
    assert resolver.require(verification.frame_map_ref).read_bytes() == sidecar.read_bytes()
    assert ServerVideoPreparationVerification.model_validate(verification.model_dump()) == verification


def test_server_rejects_forged_output_pts_even_when_sidecar_digest_is_updated(tmp_path: Path) -> None:
    resolver, upload, manifest, sidecar, observed, pts = _prepared_input(tmp_path, pts=(0, 201, 400))
    verifier = FixtureVideoVerifier(resolver, observed, pts=(0, 200, 400))

    with pytest.raises(VideoPreparationVerificationError, match="output PTS"):
        verifier.verify_and_publish(upload, manifest, sidecar)


def test_server_rejects_frame_map_above_30_fps(tmp_path: Path) -> None:
    resolver, upload, manifest, sidecar, observed, pts = _prepared_input(tmp_path, pts=(0, 100, 200))

    with pytest.raises(VideoPreparationVerificationError, match="30 FPS"):
        FixtureVideoVerifier(resolver, observed, pts).verify_and_publish(upload, manifest, sidecar)


def test_server_rejects_prepared_bytes_that_do_not_match_declared_digest(tmp_path: Path) -> None:
    resolver, upload, manifest, sidecar, observed, pts = _prepared_input(tmp_path)
    forged = manifest.model_copy(
        update={"prepared_file": manifest.prepared_file.model_copy(update={"checksum": "sha256:" + "f" * 64})}
    )

    with pytest.raises(VideoPreparationVerificationError, match="digest or size"):
        FixtureVideoVerifier(resolver, observed, pts).verify_and_publish(upload, forged, sidecar)


def test_upload_response_metadata_remains_server_private(tmp_path: Path) -> None:
    # The public FastAPI response subtype deliberately excludes both private fields.
    from src.api.studio.uploads import UploadResponse

    resolver, upload, manifest, sidecar, observed, pts = _prepared_input(tmp_path)
    report = FixtureVideoVerifier(resolver, observed, pts).verify_and_publish(upload, manifest, sidecar)
    internal = upload.model_copy(update={"video_preparation_manifest": manifest, "video_preparation": report})

    response = UploadResponse.from_record(internal).model_dump(mode="json")
    assert "video_preparation_manifest" not in response
    assert "video_preparation" not in response
    assert response["video_preparation_status"] == "verified"

    pending = UploadResponse.from_record(upload.model_copy(update={"video_preparation_manifest": manifest})).model_dump(
        mode="json"
    )
    assert pending["video_preparation_status"] == "pending"
