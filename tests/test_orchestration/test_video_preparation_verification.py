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
    prepared_bytes = b"\x00\x00\x00\x14ftypmp42" + b"prepared-video-fixture"
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


def test_staging_existing_prepared_upload_carries_the_verified_frame_map(tmp_path: Path) -> None:
    from src.models.contracts.input_assembly import InputAssemblyDeclarations
    from src.services.orchestration.inputs import InputAssemblyService
    from src.services.orchestration.jobs.database import RuntimeDatabase
    from src.services.orchestration.uploads import VideoUploadService

    resolver, upload, manifest, sidecar, observed, pts = _prepared_input(tmp_path)
    verification = FixtureVideoVerifier(resolver, observed, pts).verify_and_publish(upload, manifest, sidecar)
    database = RuntimeDatabase(f"sqlite:///{tmp_path / 'runtime.db'}")
    with database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_uploads(upload_id,payload) VALUES (?,?)", (upload.upload_id, upload.model_dump_json())
        )
    uploads = VideoUploadService(database, resolver, 10_000_000)
    uploads.save_video_preparation_manifest(upload.upload_id, manifest)
    uploads.save_video_preparation_verification(upload.upload_id, verification)

    staged = uploads.stage_for_assembly(upload.upload_id)
    assembly = InputAssemblyService(database, resolver=resolver).create(
        "user-1", [upload.upload_id], InputAssemblyDeclarations(), [], None
    )

    assert staged.source_file.checksum == upload.checksum
    assert assembly.snapshot.video_preparation_verification == verification
    assert assembly.probes[0].observed_format.value == "video_mp4"


def test_server_rejects_forged_output_pts_even_when_sidecar_digest_is_updated(tmp_path: Path) -> None:
    resolver, upload, manifest, sidecar, observed, pts = _prepared_input(tmp_path, pts=(0, 201, 400))
    verifier = FixtureVideoVerifier(resolver, observed, pts=(0, 200, 400))

    with pytest.raises(VideoPreparationVerificationError, match="output PTS"):
        verifier.verify_and_publish(upload, manifest, sidecar)


def test_server_rejects_frame_map_above_30_fps(tmp_path: Path) -> None:
    resolver, upload, manifest, sidecar, observed, pts = _prepared_input(tmp_path, pts=(0, 100, 200))

    with pytest.raises(VideoPreparationVerificationError, match="30 FPS"):
        FixtureVideoVerifier(resolver, observed, pts).verify_and_publish(upload, manifest, sidecar)


@pytest.mark.parametrize(
    ("denominator", "ticks_per_frame", "frames", "too_fast"),
    [
        (60, 1, 3, True),  # 60 FPS trên time base 1/60: trước đây lọt qua dung sai một tick
        (60, 2, 3, False),
        (45, 1, 40, True),  # 45 FPS: từng quãng nằm trong dung sai, tốc độ trung bình thì không
        (30, 1, 40, False),
        (90000, 1500, 3, True),
        (90000, 3000, 3, False),
        (30000, 1001, 3, False),  # 29,97 FPS
    ],
)
def test_30_fps_cap_holds_on_coarse_time_bases(
    denominator: int, ticks_per_frame: int, frames: int, too_fast: bool
) -> None:
    from src.models.contracts.video_preparation import PositiveRational

    time_base = PositiveRational(numerator=1, denominator=denominator)
    check = ServerVideoPreparationVerifier._faster_than_cap
    per_frame = check(ticks_per_frame, 1, time_base)
    overall = check(ticks_per_frame * (frames - 1), frames - 1, time_base)
    assert (per_frame or overall) is too_fast


def test_30_fps_cap_tolerates_millisecond_rounding_but_not_a_sustained_faster_rate() -> None:
    from src.models.contracts.video_preparation import PositiveRational

    check = ServerVideoPreparationVerifier._faster_than_cap
    milliseconds = PositiveRational(numerator=1, denominator=1000)
    pts = [round(index * 1000 / 30) for index in range(91)]  # 30 FPS làm tròn về ms: quãng 33, 33, 34
    assert not any(check(b - a, 1, milliseconds) for a, b in zip(pts, pts[1:], strict=False))
    assert not any(check(pts[n] - pts[0], n, milliseconds) for n in range(1, len(pts)))
    steady_33 = [index * 33 for index in range(91)]  # 30,3 FPS đều: từng quãng hợp lệ, cả đoạn thì quá nhanh
    assert any(check(steady_33[n] - steady_33[0], n, milliseconds) for n in range(1, len(steady_33)))


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


def _real_prepared_input(tmp_path: Path, *, rate: int, frames: int = 12):
    """MP4 H.264 thật (có B-frame) do ffmpeg sinh, kèm manifest và frame map khai đúng những gì ffprobe thấy."""
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("cần ffmpeg/ffprobe")
    upload_id = "upload-video-real-probe"
    artifact_uri = f"artifact://jobs/{upload_id}/input/source.mp4"
    resolver = ArtifactResolver(tmp_path / "artifacts")
    video_path = resolver.resolve(artifact_uri)
    video_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=64x48:rate={rate}", "-frames:v", str(frames),
        "-c:v", "libx264", "-bf", "2", "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-colorspace", "bt709", "-color_range", "tv", str(video_path),
    ]  # fmt: skip
    subprocess.run(command, check=True, timeout=120)
    verifier = ServerVideoPreparationVerifier(resolver)
    observed = verifier._probe(video_path)
    pts = tuple(verifier._presentation_pts(video_path))

    fixture = json.loads((ROOT / "fixtures/contracts/video_preparation_v1.json").read_text())
    rows = [
        {**fixture["frame_map_rows"][0], "output_frame_index": i, "output_pts": value, "source_frame_index": 2 * i, "source_pts": 2 * i}
        for i, value in enumerate(pts)
    ]  # fmt: skip
    sidecar = b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows)
    prepared_bytes = video_path.read_bytes()
    payload = fixture["preparation_manifest"]
    payload["prepared_video"] = {**observed.model_dump(mode="json"), "codec": "avc1.640028"}
    payload["source_video"]["frame_count"] = 2 * len(pts)
    payload["source_video"].update(color=payload["prepared_video"]["color"], audio_track_count=0)
    payload["audio_disposition"] = "source_has_no_audio"
    payload["prepared_file"].update(size_bytes=len(prepared_bytes), checksum=_sha(prepared_bytes))
    payload["frame_map"].update(
        size_bytes=len(sidecar), checksum=_sha(sidecar), entry_count=len(pts), source_frame_count=2 * len(pts)
    )
    payload["preparation_checksum"] = "sha256:" + "0" * 64
    payload["preparation_checksum"] = canonical_content_checksum(payload, "preparation_checksum")
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
    return verifier, upload, payload, frame_map_path, observed, pts


def test_real_ffprobe_reads_b_frame_video_in_presentation_order_and_verifies_it(tmp_path: Path) -> None:
    """Không thay ffprobe bằng fixture: video có B-frame phải cho PTS tăng dần và qua trọn bước xác minh."""
    verifier, upload, payload, sidecar, observed, pts = _real_prepared_input(tmp_path, rate=30)

    assert observed.frame_count == len(pts) == 12
    assert list(pts) == sorted(set(pts)), "PTS phải theo thứ tự trình chiếu dù luồng có B-frame"
    assert observed.color is not None and observed.color.range == "limited"
    verification = verifier.verify_and_publish(upload, ClientVideoPreparationManifest.model_validate(payload), sidecar)
    assert verification.status == "server_verified"
    assert verification.original_source_status == "client_declared_unverified"


def test_real_60_fps_video_is_rejected_by_the_profile_cap(tmp_path: Path) -> None:
    verifier, upload, payload, sidecar, _, _ = _real_prepared_input(tmp_path, rate=60)

    with pytest.raises(VideoPreparationVerificationError, match="30 FPS"):
        verifier.verify_and_publish(upload, ClientVideoPreparationManifest.model_validate(payload), sidecar)
