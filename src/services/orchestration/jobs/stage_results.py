"""Số liệu hiển thị từ receipt nhỏ, không đọc mesh, ảnh hay Gaussian."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from src.models.contracts.manifests import JobManifest, StageId, StageStatus
from src.services.orchestration.artifacts import ArtifactStoreError
from src.services.orchestration.jobs.progress import metric_confirmation_stage

if TYPE_CHECKING:
    from src.services.orchestration.projects.registry import ProjectRegistry

logger = logging.getLogger(__name__)

SCALE_SOURCES = {
    "user_measured": "Bạn đo tay",
    "ai_estimated": "Máy đề xuất từ ảnh",
    "lidar_trajectory": "Máy đề xuất từ LiDAR",
    "lidar_demo": "Đo từ LiDAR",
}


@lru_cache(maxsize=128)
def _read(resolver: Any, uri: str, checksum: str) -> dict[str, Any]:
    """Cache theo checksum bất biến; giới hạn chỉ cho metadata tối đa 4 MiB."""
    path = resolver.require_uri(uri, checksum)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Metadata vượt giới hạn đọc cho tiến trình")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Metadata phải là object")
    return value


def read_reference(resolver: Any, ref: dict[str, Any]) -> dict[str, Any]:
    return _read(resolver, ref["artifact_uri"], ref["artifact_checksum"])


def scene_results(registry: ProjectRegistry, job_id: str) -> dict[str, Any] | None:
    """Chỉ đọc head đã commit; không gọi current() vì nó có thể nhận head legacy."""
    repository = registry.scene.head_repository
    if repository is None:
        return None
    head = repository.get(job_id)
    if head is None:
        return None
    return read_reference(registry.runtime_resolver, head.scene_reference.model_dump())


def recorded_results(registry: ProjectRegistry, job: JobManifest) -> dict[str, Any]:
    """Thiếu/hỏng receipt thì bỏ riêng kết quả đó, không suy dữ liệu từ preset."""
    result: dict[str, Any] = {}
    resolver = registry.runtime_resolver
    confirmation = metric_confirmation_stage(job)
    if confirmation and confirmation.artifact_uri and confirmation.artifact_checksum:
        try:
            record = _read(resolver, confirmation.artifact_uri, confirmation.artifact_checksum)
            preview = record["preview"]
            declaration = read_reference(resolver, preview["request"]["anchor"]["measurement_ref"])
            data = declaration["input"]
            if declaration["job_id"] != job.job_id:
                raise ValueError("Xác nhận thuộc job khác")
            scale = preview["transform"]["scale_m_per_sfm_unit"]
            source = data["distance_source"]
            if source not in SCALE_SOURCES:
                raise ValueError("Nguồn tỉ lệ chưa được hỗ trợ")
            estimate = declaration.get("estimate") or {}
            methods = {
                "ai_estimated": "moge2_sparse_depth_scale_only",
                "lidar_trajectory": "lidar_trajectory_alignment",
            }
            if source in methods and estimate.get("method") != methods[source]:
                raise ValueError("Nguồn đề xuất không khớp xác nhận")
            measured = math.dist(data["check_a"], data["check_b"]) * scale
            result["metric"] = {
                "scale": scale,
                "source": source,
                "check_distance_m": data["check_distance_m"],
                "check_measured_m": measured,
                "check_error_m": abs(measured - data["check_distance_m"]),
            }
        except (ArtifactStoreError, OSError, ValueError, KeyError, TypeError) as error:
            logger.debug("Không có receipt tỉ lệ hợp lệ cho %s: %s", job.job_id, error)
    for stage in reversed(job.stage_artifacts):
        if stage.artifact_type != "ReconstructionBundle" or stage.status != StageStatus.SUCCEEDED:
            continue
        try:
            bundle = _read(resolver, stage.artifact_uri, stage.artifact_checksum)
            ref = bundle["canonical_geometry_ref"]
            source = "LiDAR" if ref["artifact_type"] == "LidarCollisionCandidate" else None
            if (
                bundle.get("rgb_geometry_ref")
                and ref["artifact_checksum"] == bundle["rgb_geometry_ref"]["artifact_checksum"]
            ):
                source = "ảnh"
            if source:
                result["collision_source"] = source
        except (ArtifactStoreError, OSError, ValueError, KeyError, TypeError) as error:
            logger.debug("Không có receipt collision hợp lệ cho %s: %s", job.job_id, error)
        break
    try:
        scene = scene_results(registry, job.job_id)
    except (ArtifactStoreError, OSError, ValueError):
        scene = None
    if scene is not None:
        objects = scene["objects"]
        result["candidate_count"] = len(objects)
        result["object_extraction"] = scene["provenance"].get("object_extraction")
        environment = scene["environment"]
        selection = environment.get("collision_selection_ref")
        if selection:
            try:
                mode = read_reference(resolver, selection)["mode"]
                result["collision_source"] = {"lidar_derived": "LiDAR", "rgb_cleaned": "ảnh"}[mode]
            except (ArtifactStoreError, OSError, ValueError, KeyError):
                result.pop("collision_source", None)
        state = scene["provenance"].get("object_geometry")
        if state in {"awaiting_review", "ready"}:
            chosen = [(item.get("provenance", {}).get("surface_selection") or {}).get("chosen") for item in objects]
            result["object_geometry"] = {
                "state": "succeeded" if state == "ready" else "pending",
                "duration_seconds": None,
                "objectgs_count": chosen.count("objectgs") if any(chosen) else None,
                "shell_count": chosen.count("gaussian_shell") if any(chosen) else None,
                "collider_count": sum(item.get("collider") is not None for item in objects),
            }
            if registry.persistence is not None:
                with registry.persistence.database.transaction() as tx:
                    row = tx.execute("SELECT payload FROM r2s_scene_requests WHERE job_id=?", (job.job_id,)).fetchone()
                if row is not None:
                    request = json.loads(row[0])
                    if (
                        request.get("mode") == "geometry"
                        and request.get("status") == "done"
                        and request.get("result_revision") == scene["scene_revision"]
                        and request.get("started_at")
                        and request.get("finished_at")
                    ):
                        elapsed = (
                            datetime.fromisoformat(request["finished_at"])
                            - datetime.fromisoformat(request["started_at"])
                        ).total_seconds()
                        if elapsed > 0:
                            result["object_geometry"]["duration_seconds"] = elapsed
    return result


def result_facts(result: dict[str, Any]) -> dict[StageId, list[tuple[str, str]]]:
    facts: dict[StageId, list[tuple[str, str]]] = {}
    metric = result.get("metric")
    if metric:
        facts[StageId.METRIC_CANONICALIZE] = [
            ("Tỉ lệ", f"{metric['scale']:.6g} m/đơn vị"),
            ("Nguồn tỉ lệ", SCALE_SOURCES[metric["source"]]),
            ("Đoạn kiểm C–D", f"{metric['check_distance_m']:.4g} m"),
            ("C–D sau quy đổi", f"{metric['check_measured_m']:.4g} m"),
            ("Sai số C–D", f"{metric['check_error_m']:.4g} m"),
        ]
    if result.get("collision_source"):
        facts[StageId.RGB_GEOMETRY] = [("Nguồn lưới va chạm", result["collision_source"])]
    if "candidate_count" in result:
        facts[StageId.OBJECT_EXTRACT] = [("Số vật ứng viên", str(result["candidate_count"]))]
    return facts
