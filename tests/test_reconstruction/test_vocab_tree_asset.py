import hashlib
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from scripts.assets.download_vocab_tree import asset as download_asset
from scripts.assets.download_vocab_tree import download_vocab_tree, main
from src.config import Settings
from src.services.reconstruction.adapters import vocab_tree as asset

Server = tuple[list[str | None], dict[str, bool]]


@pytest.fixture
def payload(monkeypatch: pytest.MonkeyPatch) -> bytes:
    data = b"verified vocabulary fixture" * 100
    for module in (asset, download_asset):
        monkeypatch.setattr(module, "VOCAB_TREE_SHA256", hashlib.sha256(data).hexdigest())
        monkeypatch.setattr(module, "VOCAB_TREE_SIZE", len(data))
        module._digest.cache_clear()
    return data


@pytest.fixture
def server(payload: bytes, monkeypatch: pytest.MonkeyPatch) -> Iterator[Server]:
    requests: list[str | None] = []
    options = {"range": True, "truncate": False, "corrupt": False, "wrong_range": False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            header = self.headers.get("Range")
            requests.append(header)
            offset = int(header.removeprefix("bytes=").removesuffix("-")) if header and options["range"] else 0
            body = payload[offset:]
            if options["corrupt"]:
                body = b"x" * len(body)
            self.send_response(206 if offset else 200)
            if offset:
                start = offset + 1 if options["wrong_range"] else offset
                self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body[: len(body) // 2] if options["truncate"] else body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(download_asset, "VOCAB_TREE_URL", f"http://127.0.0.1:{http.server_port}/vocabulary")
    try:
        yield requests, options
    finally:
        http.shutdown()
        thread.join()
        http.server_close()


def test_path_resolution_missing_valid_corrupt_and_environment(
    tmp_path: Path, payload: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "vocabulary.bin"
    monkeypatch.setattr(asset, "DEFAULT_VOCAB_TREE_PATH", path)
    settings = Settings(_env_file=None, openai_api_key="test-key", product_colmap_vocab_tree=None)
    assert asset.get_vocab_tree_path(settings) is None
    assert not asset.is_vocab_tree_available(settings)
    path.write_bytes(payload)
    assert asset.get_vocab_tree_path(settings) == path
    assert asset.is_vocab_tree_available(settings)
    # Same-size mutation must invalidate the hash cache.
    path.write_bytes(b"x" * len(payload))
    assert asset.get_vocab_tree_path(settings) is None
    monkeypatch.setenv("PRODUCT_COLMAP_VOCAB_TREE", str(path))
    configured = Settings(_env_file=None, openai_api_key="test-key")
    assert configured.product_colmap_vocab_tree == path
    path.write_bytes(payload)
    assert asset.get_vocab_tree_path(configured) == path


def test_rejects_short_files_and_directories(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / "short.bin"
    path.write_bytes(payload[:-1])
    assert not asset.verify_vocab_tree(path)
    assert not asset.verify_vocab_tree(tmp_path)


def test_download_publish_skip_and_check_only(tmp_path: Path, payload: bytes, server: Server) -> None:
    requests, _ = server
    path = tmp_path / "tree.bin"
    assert main(["--output", str(path), "--check-only"]) == 1
    assert requests == []
    assert download_vocab_tree(path) == path
    assert path.read_bytes() == payload
    assert not path.with_suffix(".bin.part").exists()
    assert download_vocab_tree(path) == path
    assert main(["--output", str(path), "--check-only"]) == 0
    assert requests == [None]


@pytest.mark.parametrize("range_supported", [True, False])
def test_resume_or_restart_if_server_ignores_range(
    tmp_path: Path, payload: bytes, server: Server, range_supported: bool
) -> None:
    requests, options = server
    options["range"] = range_supported
    path = tmp_path / "tree.bin"
    path.with_suffix(".bin.part").write_bytes(payload[:100])
    download_vocab_tree(path)
    assert requests == ["bytes=100-"]
    assert path.read_bytes() == payload


def test_incomplete_transfer_resumes_without_publishing(tmp_path: Path, payload: bytes, server: Server) -> None:
    requests, options = server
    options["truncate"] = True
    path = tmp_path / "tree.bin"
    assert main(["--output", str(path)]) == 1
    assert not path.exists()
    partial = path.with_suffix(".bin.part")
    offset = partial.stat().st_size
    assert 0 < offset < len(payload)
    options["truncate"] = False
    download_vocab_tree(path)
    assert requests[-1] == f"bytes={offset}-"
    assert path.read_bytes() == payload


def test_wrong_resume_header_and_corrupt_download_never_publish(tmp_path: Path, payload: bytes, server: Server) -> None:
    _, options = server
    path = tmp_path / "tree.bin"
    partial = path.with_suffix(".bin.part")
    partial.write_bytes(payload[:100])
    options["wrong_range"] = True
    assert main(["--output", str(path)]) == 1
    assert not path.exists()
    assert partial.read_bytes() == payload[:100]
    options["wrong_range"] = False
    options["corrupt"] = True
    assert main(["--output", str(path)]) == 1
    assert not path.exists()
    assert not partial.exists()


def test_complete_partial_is_verified_before_publish(tmp_path: Path, payload: bytes, server: Server) -> None:
    requests, _ = server
    path = tmp_path / "tree.bin"
    path.with_suffix(".bin.part").write_bytes(payload)
    download_vocab_tree(path)
    assert path.read_bytes() == payload
    assert requests == []


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_does_not_create_files(tmp_path: Path, timeout: float) -> None:
    path = tmp_path / "new" / "tree.bin"
    with pytest.raises(ValueError, match="Timeout"):
        download_vocab_tree(path, timeout)
    assert not path.parent.exists()
