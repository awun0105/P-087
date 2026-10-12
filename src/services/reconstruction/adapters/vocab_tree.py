"""Pinned COLMAP 256K vocabulary asset, independent of job artifacts."""

from __future__ import annotations

import hashlib
import stat
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src.config import Settings

# demuc.de/colmap links to this official release; its old clustering URL returns 404.
VOCAB_TREE_URL = "https://github.com/colmap/colmap/releases/download/3.11.1/vocab_tree_flickr100K_words256K.bin"
# Project pin measured from the official release bytes, not a publisher-signed checksum.
VOCAB_TREE_SHA256 = "d2055600452a531b5b0a62aa5943e1a07195273dc4eeebcf23d3a924d881d53a"
VOCAB_TREE_SIZE = 117_893_693
DEFAULT_VOCAB_TREE_PATH = (
    Path(__file__).resolve().parents[4] / "data/checkpoints/colmap/vocab_tree_clustering_flickr100k_words256K.bin"
)
VocabularyFormat = Literal["flann", "faiss"]
FAISS_VOCAB_TREE_URL = (
    "https://github.com/colmap/colmap/releases/download/3.11.1/vocab_tree_faiss_flickr100K_words256K.bin"
)
FAISS_VOCAB_TREE_SHA256 = "96ca8ec8ea60b1f73465aaf2c401fd3b3ca75cdba2d3c50d6a2f6f760f275ddc"
FAISS_VOCAB_TREE_SIZE = 72_412_636
DEFAULT_FAISS_VOCAB_TREE_PATH = DEFAULT_VOCAB_TREE_PATH.with_name("vocab_tree_faiss_flickr100K_words256K.bin")


def vocab_tree_spec(format: VocabularyFormat) -> tuple[str, str, int, Path]:
    """FLANN for COLMAP <3.12, FAISS for newer runtimes; each format has its own pin."""
    if format == "faiss":
        return FAISS_VOCAB_TREE_URL, FAISS_VOCAB_TREE_SHA256, FAISS_VOCAB_TREE_SIZE, DEFAULT_FAISS_VOCAB_TREE_PATH
    return VOCAB_TREE_URL, VOCAB_TREE_SHA256, VOCAB_TREE_SIZE, DEFAULT_VOCAB_TREE_PATH


def _signature(path: Path) -> tuple[int, int, int, int, int]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Vocabulary asset must be a regular file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@lru_cache(maxsize=8)
def _digest(path: Path, _signature: tuple[int, int, int, int, int]) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_vocab_tree(path: Path, format: VocabularyFormat = "flann") -> bool:
    """Reject partial/corrupt assets; invalidate cached hashes when bytes change."""
    try:
        _, checksum, size, _ = vocab_tree_spec(format)
        before = _signature(path)
        return before[2] == size and _digest(path, before) == checksum and _signature(path) == before
    except (OSError, ValueError):
        return False


def get_vocab_tree_path(settings: Settings | None = None, *, format: VocabularyFormat = "flann") -> Path | None:
    """Resolve an explicit deployment path or the standard repo asset; never download at request time."""
    if settings is None:
        from src.config import get_settings

        settings = get_settings()
    path = (settings.product_colmap_vocab_tree or vocab_tree_spec(format)[3]).expanduser().resolve()
    return path if verify_vocab_tree(path, format) else None


def is_vocab_tree_available(settings: Settings | None = None, *, format: VocabularyFormat = "flann") -> bool:
    return get_vocab_tree_path(settings, format=format) is not None
