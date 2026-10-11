"""Trọng số EgoBlur đi qua kho file của deployment: pod mới tự tải, file sai không bao giờ được dùng."""

import hashlib
from pathlib import Path

import pytest

from scripts.gpu import egoblur_weights
from scripts.gpu.egoblur_weights import WeightsError, fetch, upload
from src.services.orchestration.artifacts import ArtifactRemote
from tests.test_orchestration.memory_object_store import MemoryObjectStore


@pytest.fixture
def weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Hai file giả với checksum ghim tương ứng (file thật nặng vài trăm MB và cần đồng ý giấy phép)."""
    source = tmp_path / "source"
    source.mkdir()
    pinned = {}
    for name in egoblur_weights.WEIGHTS:
        (source / name).write_bytes(name.encode())
        pinned[name] = "sha256:" + hashlib.sha256(name.encode()).hexdigest()
    monkeypatch.setattr(egoblur_weights, "WEIGHTS", pinned)
    return source


def test_upload_once_then_any_new_pod_fetches_and_later_starts_are_no_ops(weights: Path, tmp_path: Path) -> None:
    remote = ArtifactRemote(MemoryObjectStore(), "prod")
    assert sorted(upload(remote, weights)) == sorted(egoblur_weights.WEIGHTS)
    upload(remote, weights)  # chạy lại không lỗi

    pod = tmp_path / "pod" / "egoblur"
    assert sorted(fetch(remote, pod)) == sorted(egoblur_weights.WEIGHTS)
    assert all((pod / name).read_bytes() == name.encode() for name in egoblur_weights.WEIGHTS)
    assert fetch(remote, pod) == []
    assert fetch(None, pod) == [], "đã có đủ file đúng checksum thì không cần kho file"


def test_corrupt_local_file_is_replaced_and_wrong_bytes_are_never_accepted(weights: Path, tmp_path: Path) -> None:
    remote = ArtifactRemote(MemoryObjectStore(), "prod")
    upload(remote, weights)
    pod = tmp_path / "pod"
    fetch(remote, pod)
    name = next(iter(egoblur_weights.WEIGHTS))
    (pod / name).write_bytes(b"truncated")
    assert fetch(remote, pod) == [name] and (pod / name).read_bytes() == name.encode()

    (weights / name).write_bytes(b"not the real weights")
    with pytest.raises(WeightsError, match="sai checksum"):
        upload(ArtifactRemote(MemoryObjectStore(), "prod"), weights)


def test_missing_weights_fail_with_an_instruction_instead_of_starting_a_worker_without_them(
    weights: Path, tmp_path: Path
) -> None:
    with pytest.raises(WeightsError, match="upload"):
        fetch(ArtifactRemote(MemoryObjectStore(), "prod"), tmp_path / "pod")
    with pytest.raises(WeightsError, match="ARTIFACT_S3"):
        fetch(None, tmp_path / "pod")
    assert not list((tmp_path / "pod").glob("*.jit"))
