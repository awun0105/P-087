"""Lớp LiDAR chồng lên scene (ADR 0009, L11): file điểm đã thu gọn, dựng một lần rồi phục vụ từ cache.

File là dữ liệu dẫn xuất để hiển thị, không phải artifact: nằm cạnh kho artifact, khoá theo checksum của bản ghi căn
chỉnh nên bundle mới (căn chỉnh mới) tự có file mới và trình duyệt cache dài hạn được.
"""

from pathlib import Path

from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.reconstruction import lidar_overlay_points


def lidar_overlay_key(registry: ProjectRegistry, job_id: str) -> str | None:
    """Khoá của lớp LiDAR (checksum bản ghi căn chỉnh); None khi scene không có LiDAR đã căn chỉnh."""
    bundle = job_bundle(registry, registry.get_job(job_id))
    record = bundle.alignment_record if bundle is not None else None
    if record is None or bundle is None or bundle.lidar_geometry_ref is None:
        return None
    return record.artifact_checksum.removeprefix("sha256:")


def lidar_overlay_file(registry: ProjectRegistry, job_id: str, cache_dir: Path) -> Path | None:
    """File float32 little-endian `x y z` liên tiếp (mét, Z-up, hệ `world`); None khi scene không có lớp LiDAR."""
    key = lidar_overlay_key(registry, job_id)
    if key is None:
        return None
    target = cache_dir / f"{key}.xyz.f32"
    if target.is_file():
        return target
    bundle = job_bundle(registry, registry.get_job(job_id))
    points = lidar_overlay_points(bundle, registry.runtime_resolver.require)
    if points is None:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Ghi qua file tạm rồi đổi tên: request song song không bao giờ đọc phải file dở.
    partial = target.with_name(f"{target.name}.{id(points):x}.partial")
    partial.write_bytes(points.tobytes())
    partial.replace(target)
    return target
