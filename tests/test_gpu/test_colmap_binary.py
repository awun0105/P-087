"""Gói nhị phân COLMAP (T-038 bước 2): đẩy/tải có kiểm sha256, từ chối gói sai, idempotent. Không gọi mạng thật."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from scripts.gpu import colmap_binary as cb
from src.services.orchestration.artifacts import ArtifactStoreError

REPO = Path(__file__).resolve().parents[2]
PAYLOAD = b"colmap bundle bytes for tests"
PAYLOAD_HEX = hashlib.sha256(PAYLOAD).hexdigest()


class FakeRemote:
    def __init__(self, payload: bytes | None = PAYLOAD) -> None:
        self.payload = payload
        self.pushed: list[tuple[str, Path]] = []
        self.fetched: list[tuple[str, str | None]] = []

    def push(self, key: str, path: Path) -> None:
        self.pushed.append((key, path))

    def fetch(self, key: str, destination: Path, expected_checksum: str | None = None) -> None:
        self.fetched.append((key, expected_checksum))
        if self.payload is None:
            raise ArtifactStoreError("không có đối tượng")
        destination.write_bytes(self.payload)


def _bundle(tmp_path: Path, content: bytes = PAYLOAD) -> Path:
    path = tmp_path / "colmap-bundle.tar.zst"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_remote_path_follows_the_image_digest() -> None:
    image = "colmap/colmap@sha256:b8498ebecab11c3f9b9a25370e3fcfb6de9b6bcd4f3c85d5dc39a40229f40954"
    assert cb.remote_path(image) == "runtime-binaries/colmap-b8498ebecab1/colmap-bundle.tar.zst"


def test_pinned_bundle_checksum_is_a_real_sha256() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", cb.pinned("COLMAP_BINARY_SHA"))


def test_upload_pushes_a_bundle_that_matches_the_checksum(tmp_path: Path) -> None:
    remote = FakeRemote()
    key = cb.upload(remote, _bundle(tmp_path), PAYLOAD_HEX)
    assert key == cb.remote_path(cb.pinned("COLMAP_IMAGE"))
    assert remote.pushed == [(key, tmp_path / "colmap-bundle.tar.zst")]


def test_upload_refuses_a_bundle_with_the_wrong_checksum(tmp_path: Path) -> None:
    remote = FakeRemote()
    with pytest.raises(cb.BundleError, match="sai sha256"):
        cb.upload(remote, _bundle(tmp_path, "gói khác".encode()), PAYLOAD_HEX)
    assert remote.pushed == []


def test_fetch_from_file_copies_a_valid_bundle_and_is_idempotent(tmp_path: Path) -> None:
    source = _bundle(tmp_path / "src")
    out = tmp_path / "out" / "colmap-bundle.tar.zst"
    assert cb.fetch(None, out, PAYLOAD_HEX, from_file=source) is True
    assert out.read_bytes() == PAYLOAD
    assert cb.fetch(None, out, PAYLOAD_HEX, from_file=source) is False


def test_fetch_from_file_refuses_a_wrong_bundle_and_leaves_no_output(tmp_path: Path) -> None:
    source = _bundle(tmp_path / "src", "hỏng".encode())
    out = tmp_path / "out" / "colmap-bundle.tar.zst"
    with pytest.raises(cb.BundleError, match="sai sha256"):
        cb.fetch(None, out, PAYLOAD_HEX, from_file=source)
    assert not out.exists()


def test_fetch_from_the_store_checks_the_expected_checksum(tmp_path: Path) -> None:
    remote = FakeRemote()
    out = tmp_path / "colmap-bundle.tar.zst"
    assert cb.fetch(remote, out, PAYLOAD_HEX) is True
    assert remote.fetched == [(cb.remote_path(cb.pinned("COLMAP_IMAGE")), f"sha256:{PAYLOAD_HEX}")]


def test_fetch_without_store_or_file_says_what_is_missing(tmp_path: Path) -> None:
    with pytest.raises(cb.BundleError, match="ARTIFACT_S3_"):
        cb.fetch(None, tmp_path / "colmap-bundle.tar.zst", PAYLOAD_HEX)


def test_store_failure_is_reported_with_the_upload_hint(tmp_path: Path) -> None:
    with pytest.raises(cb.BundleError, match="upload"):
        cb.fetch(FakeRemote(payload=None), tmp_path / "colmap-bundle.tar.zst", PAYLOAD_HEX)


def test_export_copies_real_files_and_fetches_licenses_by_pinned_checksum() -> None:
    text = (REPO / "scripts/gpu/export_colmap_binary.sh").read_text(encoding="utf-8")
    assert text.count("docker cp -L") >= 2, "chép file thật, không chép symlink"
    assert '"$(pin COLMAP_LICENSE_SHA)"' in text and '"$(pin ONNXRUNTIME_LICENSE_SHA)"' in text
    assert "zstd -19" in text
    assert 'tar -C "$WORK" -cf - colmap' in text
