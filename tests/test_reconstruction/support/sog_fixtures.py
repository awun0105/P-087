"""Small synthetic SOG-v2 packages for bounded input-classification tests."""

import io
import json
import zipfile
from typing import Any


def sog_archive(
    *,
    version: Any = 2,
    model: Any = None,
    sh_bands: int = 0,
    count: int = 4,
    means_mins: Any = (-1.0, -1.0, -1.0),
    means_maxs: Any = (1.0, 1.0, 1.0),
) -> bytes:
    """Return an archive with valid metadata and bounded one-pixel WebP header fixtures."""
    meta: dict[str, Any] = {
        "version": version,
        "count": count,
        "means": {"mins": means_mins, "maxs": means_maxs, "files": ["means_l.webp", "means_u.webp"]},
        "scales": {"codebook": [0.0] * 256, "files": ["scales.webp"]},
        "quats": {"files": ["quats.webp"]},
        "sh0": {"codebook": [0.0] * 256, "files": ["sh0.webp"]},
    }
    if model is not None:
        meta["model"] = model
    files = ["means_l.webp", "means_u.webp", "scales.webp", "quats.webp", "sh0.webp"]
    if sh_bands:
        meta["shN"] = {
            "count": 4,
            "bands": sh_bands,
            "codebook": [0.0] * 256,
            "files": ["shN_centroids.webp", "shN_labels.webp"],
        }
        files.extend(("shN_centroids.webp", "shN_labels.webp"))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("meta.json", json.dumps(meta, separators=(",", ":")))
        for filename in files:
            archive.writestr(filename, b"RIFF\x12\x00\x00\x00WEBPVP8L\x05\x00\x00\x00\x2f\x00\x00\x00\x00\x00")
    return output.getvalue()
