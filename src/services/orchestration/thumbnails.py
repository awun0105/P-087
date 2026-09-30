"""Ảnh xem trước nhỏ của scene cho màn Scenes: frame đầu tiên đã trích, thu về JPEG 480 px.

Không phải artifact: là cache dẫn xuất trên đĩa của API, khoá theo checksum của frame nguồn
(frame bất biến nên cache không cần làm mới). Thẻ scene khỏi phải tải PNG gốc ~1,4 MB.
"""

import logging
import subprocess
from pathlib import Path

from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.stage_views import job_frame_images

logger = logging.getLogger(__name__)

THUMBNAIL_WIDTH = 480


def scene_thumbnail(registry: ProjectRegistry, job_id: str, cache_dir: Path, ffmpeg: str = "ffmpeg") -> Path | None:
    """JPEG thu nhỏ của frame đầu; None khi job chưa trích frame hoặc không tạo được ảnh."""
    frames = job_frame_images(registry, registry.get_job(job_id))
    if not frames:
        return None
    first = frames[0]
    target = cache_dir / f"{first.artifact_checksum.removeprefix('sha256:')}-{THUMBNAIL_WIDTH}.jpg"
    if target.is_file():
        return target
    source = registry.runtime_resolver.require(first)
    cache_dir.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial.jpg")
    try:
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-vf",
                f"scale={THUMBNAIL_WIDTH}:-2",
                "-q:v",
                "4",
                str(partial),
            ],
            check=True,
            timeout=30,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Không tạo được thumbnail job=%s cause=%s", job_id, type(error).__name__)
        partial.unlink(missing_ok=True)
        return None
    partial.replace(target)
    return target
