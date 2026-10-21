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


def test_faiss_asset_has_a_separate_pin_and_explicit_format(
    tmp_path: Path, payload: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "faiss.bin"
    faiss = b"faiss" + payload
    path.write_bytes(faiss)
    for module in (asset, download_asset):
        monkeypatch.setattr(module, "FAISS_VOCAB_TREE_SHA256", hashlib.sha256(faiss).hexdigest())
        monkeypatch.setattr(module, "FAISS_VOCAB_TREE_SIZE", len(faiss))
    settings = Settings(_env_file=None, openai_api_key="test-key", product_colmap_vocab_tree=path)
    assert asset.get_vocab_tree_path(settings, format="faiss") == path
    assert asset.get_vocab_tree_path(settings, format="flann") is None
    assert main(["--output", str(path), "--format", "faiss", "--check-only"]) == 0
    assert main(["--output", str(path), "--format", "flann", "--check-only"]) == 1


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


# --- T-071 B: từ điển bake vào image GPU và mục preflight bắt buộc ----------------------------------------------------

REPO = Path(__file__).resolve().parents[2]


def _faiss_pin(monkeypatch: pytest.MonkeyPatch, data: bytes, default: Path) -> None:
    for module in (asset, download_asset):
        monkeypatch.setattr(module, "FAISS_VOCAB_TREE_SHA256", hashlib.sha256(data).hexdigest())
        monkeypatch.setattr(module, "FAISS_VOCAB_TREE_SIZE", len(data))
        monkeypatch.setattr(module, "DEFAULT_FAISS_VOCAB_TREE_PATH", default)
        module._digest.cache_clear()


def test_format_follows_the_colmap_release_and_the_file_header(tmp_path: Path) -> None:
    assert asset.vocabulary_format("COLMAP 4.0.1 (Commit 1a2b) with CUDA") == "faiss"
    assert asset.vocabulary_format("COLMAP 3.12.0") == "faiss"
    assert asset.vocabulary_format("COLMAP 3.11.1") == "flann"
    assert asset.vocabulary_format("colmap help") is None
    faiss, flann = tmp_path / "faiss.bin", tmp_path / "flann.bin"
    faiss.write_bytes((2).to_bytes(4, "little") + b"x")
    flann.write_bytes((262144).to_bytes(4, "little") + b"x")
    assert asset.file_format(faiss) == "faiss" and asset.file_format(flann) == "flann"


def test_image_bakes_the_pinned_format_at_the_path_the_runtime_reads() -> None:
    dockerfile = (REPO / "Dockerfile.gpu").read_text(encoding="utf-8")
    pins = dict(
        line.split("=", 1)
        for line in (REPO / "configs/runtime/pins.env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    # COLMAP_IMAGE là COLMAP 4.x → FAISS; preflight kiểm lại theo phiên bản thật của binary trong image.
    assert pins["COLMAP_VOCAB_FORMAT"] == "faiss"
    run = dockerfile.index("download_vocab_tree.py --format")
    assert dockerfile.index("uv venv --python") < run < dockerfile.index("\nCOPY . .\n")
    assert "s/^COLMAP_VOCAB_FORMAT=//p' configs/runtime/pins.env" in dockerfile
    assert '--format "$format" --check-only' in dockerfile
    assert "COPY src/services/reconstruction/adapters/vocab_tree.py" in dockerfile
    # Mặc định của script tải = đường dẫn worker đọc khi không đặt PRODUCT_COLMAP_VOCAB_TREE; `data/` không vào
    # build context nên lớp code không đè lên file đã bake.
    _, checksum, size, path = asset.vocab_tree_spec("faiss")
    assert path.relative_to(REPO).as_posix() == "data/checkpoints/colmap/vocab_tree_faiss_flickr100K_words256K.bin"
    assert (
        download_asset.vocab_tree_spec("faiss")[1:3]
        == (checksum, size)
        == (
            asset.FAISS_VOCAB_TREE_SHA256,
            asset.FAISS_VOCAB_TREE_SIZE,
        )
    )
    assert "data/" in (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()


def test_default_output_check_selects_the_faiss_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"\x01\x00\x00\x00faiss vocabulary fixture" * 10
    default = tmp_path / "data/checkpoints/colmap/vocab_tree_faiss_flickr100K_words256K.bin"
    _faiss_pin(monkeypatch, data, default)
    assert main(["--format", "faiss", "--check-only"]) == 1
    default.parent.mkdir(parents=True)
    default.write_bytes(data)
    assert main(["--format", "faiss", "--check-only"]) == 0
    assert main(["--format", "flann", "--check-only", "--output", str(default)]) == 1


def test_faiss_download_uses_its_own_url_and_checksum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"\x01\x00\x00\x00faiss vocabulary fixture" * 10
    default = tmp_path / "tree.bin"
    _faiss_pin(monkeypatch, data, default)
    served: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            served.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(download_asset, "FAISS_VOCAB_TREE_URL", f"http://127.0.0.1:{http.server_port}/faiss")
    try:
        assert download_vocab_tree(default, format="faiss") == default
    finally:
        http.shutdown()
        thread.join()
        http.server_close()
    assert served == ["/faiss"]
    assert default.read_bytes() == data


def test_preflight_vocabulary_item_is_required_and_checks_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from scripts.kaggle import preflight

    entry = next(item for item in preflight.CHECKS if item[0] == "Từ điển COLMAP")
    assert entry[1] is preflight.colmap_vocabulary and entry[2] is True
    data = b"\x01\x00\x00\x00faiss vocabulary fixture" * 10
    path = tmp_path / "tree.bin"
    _faiss_pin(monkeypatch, data, path)
    # Máy dev có thể đã tải cây FLANN thật vào repo: test không đọc nó.
    monkeypatch.setattr(asset, "DEFAULT_VOCAB_TREE_PATH", tmp_path / "flann-missing.bin")
    version = {"text": "COLMAP 4.0.1 (Commit abc)\n"}
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=version["text"], stderr=""),
    )
    monkeypatch.delenv("PRODUCT_COLMAP_VOCAB_TREE", raising=False)
    monkeypatch.delenv("R2S_COLMAP_COMMAND", raising=False)
    monkeypatch.delenv("REC03_COLMAP_COMMAND", raising=False)
    assert preflight.colmap_vocabulary() == (False, "chưa đặt R2S_COLMAP_COMMAND")
    monkeypatch.setenv("R2S_COLMAP_COMMAND", '["colmap"]')
    ok, detail = preflight.colmap_vocabulary()
    assert not ok and "thiếu từ điển faiss" in detail
    path.write_bytes(data)
    assert preflight.colmap_vocabulary() == (True, "faiss, checksum khớp (tree.bin)")
    version["text"] = "COLMAP 3.9.1\n"  # binary cũ cần FLANN: cây FAISS không đạt
    ok, detail = preflight.colmap_vocabulary()
    assert not ok and "flann" in detail
    version["text"] = "usage: colmap\n"
    assert preflight.colmap_vocabulary()[0] is False
    version["text"] = "COLMAP 4.0.1\n"
    monkeypatch.setenv("PRODUCT_COLMAP_VOCAB_TREE", str(tmp_path / "missing.bin"))
    assert preflight.colmap_vocabulary()[0] is False
