"""TorWIC source adapter: logical input refs -> canonical normalized PNG bytes."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.identity import canonical_content_checksum, verify_content_checksum
from src.models.contracts.manifests import InputFile, InputManifest
from src.services.reconstruction.rgb.frame_set import _sha256


@dataclass(frozen=True)
class TorwicFrameSourceConfig:
    """Dataset paths chỉ xuất hiện tại TorWIC adapter boundary."""

    dataset_root: Path
    traversal_id: str
    inventory_path: Path


class TorwicFrameSource:
    """Bind REC-02 inventory với InputManifest trước khi resolve source URI."""

    def __init__(self, config: TorwicFrameSourceConfig, manifest: InputManifest) -> None:
        verify_content_checksum(manifest, "input_manifest_checksum")
        if re.fullmatch(r"[A-Za-z0-9_-]+", config.traversal_id) is None:
            raise ValueError("invalid TorWIC traversal ID")
        inventory = json.loads(config.inventory_path.read_text())
        if inventory.get("inventory_checksum") != canonical_content_checksum(inventory, "inventory_checksum"):
            raise ValueError("TorWIC frame inventory checksum mismatch")
        if inventory.get("input_manifest_checksum") != manifest.input_manifest_checksum:
            raise ValueError("TorWIC frame inventory belongs to another input")
        rows = inventory["frames"]
        if len(rows) != len(manifest.files) or not rows:
            raise ValueError("TorWIC frame inventory is incomplete")
        self.paths: dict[str, tuple[Path, str]] = {}
        root = config.dataset_root / "normalized" / config.traversal_id.lower() / "rgb_frames"
        for row, file in zip(rows, manifest.files, strict=True):
            self._index_row(row, file, root)
        if len(self.paths) != len(rows):
            raise ValueError("TorWIC frame inventory contains duplicate artifact URIs")

    def _index_row(self, row: dict, file: InputFile, root: Path) -> None:
        frame_id = row["frame_id"]
        expected_name = f"{frame_id:06d}.png"
        if (
            file.original_name != expected_name
            or file.media_type != "image/png"
            or row["artifact_uri"] != file.artifact_uri
            or row["checksum"] != file.checksum
            or row["size_bytes"] != file.size_bytes
            or file.data_class != ArtifactDataClass.PRODUCT_INPUT
        ):
            raise ValueError("TorWIC frame row differs from InputManifest")
        self.paths[file.artifact_uri] = (root / expected_name, file.checksum)

    def resolve(self, reference: ProductArtifactRef) -> Path:
        """Return source path only for an exact checksummed product input ref."""
        entry = self.paths.get(reference.artifact_uri)
        if entry is None or reference.data_class != ArtifactDataClass.PRODUCT_INPUT:
            raise ValueError("RGB input artifact is not in the approved inventory")
        path, checksum = entry
        if reference.artifact_checksum != checksum or not path.is_file() or _sha256(path) != checksum:
            raise ValueError("RGB input artifact bytes differ from the inventory")
        return path

    def resolve_uri(self, artifact_uri: str) -> Path:
        """Upstream InputManifest URI resolution; byte check remains required."""
        entry = self.paths.get(artifact_uri)
        if entry is None:
            raise ValueError("RGB input URI is not in the approved inventory")
        path, checksum = entry
        if not path.is_file() or _sha256(path) != checksum:
            raise ValueError("RGB input bytes differ from the inventory")
        return path
