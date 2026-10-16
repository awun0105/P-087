"""REC-03 input boundary: consume REC-02A frame-set artifact directly."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from src.models.contracts.artifacts import ProductArtifactRef
from src.services.reconstruction.rgb.frames.frame_set import FrameSetResolver, frame_image_name


@dataclass(frozen=True)
class ColmapImageInput:
    """Isolated COLMAP image directory cùng nguồn frame-set bất biến."""

    image_dir: Path
    frame_ids: tuple[int, ...]
    frame_set_checksum: str
    source_reference: ProductArtifactRef


class ColmapInputAdapter:
    """COLMAP cần directory ảnh; workspace copy không chia inode với source."""

    def __init__(self, frame_sets: FrameSetResolver) -> None:
        self.frame_sets = frame_sets

    def prepare(self, reference: ProductArtifactRef, workspace: Path) -> ColmapImageInput:
        """Giữ byte và định dạng ảnh nguồn, không nhận private folder làm input contract."""
        frame_set = self.frame_sets.load(reference)
        rows = self.frame_sets.materialize(frame_set)
        image_dir = workspace / "images"
        if image_dir.exists():
            raise ValueError("COLMAP image workspace already exists")
        image_dir.mkdir(parents=True)
        try:
            for frame_id, source, _ in rows:
                destination = image_dir / frame_image_name(frame_id, source)
                shutil.copyfile(source, destination)
        except (OSError, ValueError):
            shutil.rmtree(image_dir)
            raise
        return ColmapImageInput(image_dir, tuple(row[0] for row in rows), frame_set.frame_set_checksum, reference)
