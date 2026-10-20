"""Số liệu hiển thị từ receipt nhỏ, không đọc mesh, ảnh hay Gaussian."""

from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from typing import TYPE_CHECKING, Any, NamedTuple

from src.models.contracts.manifests import JobManifest, StageId, StageStatus
from src.services.orchestration.artifacts import ArtifactResolver, ArtifactStoreError
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


def _read(resolver: ArtifactResolver, uri: str, checksum: str) -> dict[str, Any]:
    """Đọc và kiểm checksum; tài liệu gốc không được giữ trong cache."""
    path = resolver.require_uri(uri, checksum)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Metadata vượt giới hạn đọc cho tiến trình")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Metadata phải là object")
    return value


def read_reference(resolver: ArtifactResolver, ref: dict[str, Any]) -> dict[str, Any]:
    return _read(resolver, ref["artifact_uri"], ref["artifact_checksum"])


class _SceneSummary(NamedTuple):
    candidate_count: int
    object_extraction: str | None
    collision_selection_ref: tuple[tuple[str, str], ...] | None
    collision_source_ref: tuple[tuple[str, str], ...] | None
    geometry_state: str | None
    chosen: tuple[str | None, ...]
    collider_count: int
    scene_revision: str


@lru_cache(maxsize=256)
def _scene_summary(resolver: ArtifactResolver, uri: str, checksum: str) -> _SceneSummary:
    scene = _read(resolver, uri, checksum)
    objects = [item for item in scene["objects"] if item.get("origin") == "reconstructed"]
    environment = scene["environment"]
    selection = environment.get("collision_selection_ref")
    source = environment.get("collision_source_ref")
    return _SceneSummary(
        len(objects),
        scene["provenance"].get("object_extraction"),
        tuple(selection.items()) if selection else None,
        tuple(source.items()) if source else None,
        scene["provenance"].get("object_geometry"),
        tuple((item.get("provenance", {}).get("surface_selection") or {}).get("chosen") for item in objects),
        sum(item.get("collider") is not None for item in objects),
        scene["scene_revision"],
    )


def scene_results(registry: ProjectRegistry, job_id: str) -> _SceneSummary | None:
    """Chỉ đọc head đã commit; cache tuple rút gọn theo URI và checksum của revision."""
    repository = registry.scene.head_repository
    if repository is None:
        return None
    head = repository.get(job_id)
    if head is None:
        return None
    ref = head.scene_reference
    return _scene_summary(registry.runtime_resolver, ref.artifact_uri, ref.artifact_checksum)


@lru_cache(maxsize=256)
def _metric_summary(
    resolver: ArtifactResolver, uri: str, checksum: str, job_id: str
) -> tuple[float, str, float, float, float]:
    record = _read(resolver, uri, checksum)
    preview = record["preview"]
    declaration = read_reference(resolver, preview["request"]["anchor"]["measurement_ref"])
    data = declaration["input"]
    if declaration["job_id"] != job_id:
        raise ValueError("Xác nhận thuộc job khác")
    scale = preview["transform"]["scale_m_per_sfm_unit"]
    source = data["distance_source"]
    if source not in SCALE_SOURCES:
        raise ValueError("Nguồn tỉ lệ chưa được hỗ trợ")
    estimate = declaration.get("estimate") or {}
    methods = {"ai_estimated": "moge2_sparse_depth_scale_only", "lidar_trajectory": "lidar_trajectory_alignment"}
    if source in methods and estimate.get("method") != methods[source]:
        raise ValueError("Nguồn đề xuất không khớp xác nhận")
    measured = math.dist(data["check_a"], data["check_b"]) * scale
    return scale, source, data["check_distance_m"], measured, abs(measured - data["check_distance_m"])


@lru_cache(maxsize=256)
def _collision_summary(
    resolver: ArtifactResolver, uri: str, checksum: str
) -> tuple[str | None, tuple[tuple[str, str], ...]]:
    bundle = _read(resolver, uri, checksum)
    ref = bundle["canonical_geometry_ref"]
    source = "LiDAR" if ref["artifact_type"] == "LidarCollisionCandidate" else None
    if bundle.get("rgb_geometry_ref") and ref["artifact_checksum"] == bundle["rgb_geometry_ref"]["artifact_checksum"]:
        source = "ảnh"
    return source, tuple(ref.items())


def recorded_results(registry: ProjectRegistry, job: JobManifest) -> dict[str, Any]:
    """Thiếu/hỏng receipt thì bỏ riêng kết quả đó, không suy dữ liệu từ preset."""
    result: dict[str, Any] = {}
    resolver = registry.runtime_resolver
    confirmation = metric_confirmation_stage(job)
    if confirmation and confirmation.artifact_uri and confirmation.artifact_checksum:
        try:
            values = _metric_summary(resolver, confirmation.artifact_uri, confirmation.artifact_checksum, job.job_id)
            result["metric"] = dict(
                zip(("scale", "source", "check_distance_m", "check_measured_m", "check_error_m"), values, strict=True)
            )
        except (ArtifactStoreError, OSError, ValueError, KeyError, TypeError) as error:
            logger.debug("Không có receipt tỉ lệ hợp lệ cho %s: %s", job.job_id, error)
    for stage in reversed(job.stage_artifacts):
        if stage.artifact_type != "ReconstructionBundle" or stage.status != StageStatus.SUCCEEDED:
            continue
        try:
            source, ref = _collision_summary(resolver, stage.artifact_uri, stage.artifact_checksum)
            if source:
                result["collision_source"] = source
                result["collision_ref"] = dict(ref)
        except (ArtifactStoreError, OSError, ValueError, KeyError, TypeError) as error:
            logger.debug("Không có receipt collision hợp lệ cho %s: %s", job.job_id, error)
        break
    try:
        scene = scene_results(registry, job.job_id)
    except (ArtifactStoreError, OSError, ValueError):
        scene = None
    if scene is not None:
        result["candidate_count"] = scene.candidate_count
        result["object_extraction"] = scene.object_extraction
        selection = scene.collision_selection_ref
        if selection:
            try:
                mode = read_reference(resolver, dict(selection))["mode"]
                result["collision_source"] = {"lidar_derived": "LiDAR", "rgb_cleaned": "ảnh"}[mode]
                result["collision_ref"] = dict(scene.collision_source_ref) if scene.collision_source_ref else None
            except (ArtifactStoreError, OSError, ValueError, KeyError):
                result.pop("collision_source", None)
                result.pop("collision_ref", None)
        state = scene.geometry_state
        if state in {"awaiting_review", "ready"}:
            chosen = scene.chosen
            result["object_geometry"] = {
                "state": "succeeded" if state == "ready" else "pending",
                "duration_seconds": None,
                "objectgs_count": chosen.count("objectgs") if any(chosen) else None,
                "shell_count": chosen.count("gaussian_shell") if any(chosen) else None,
                "collider_count": scene.collider_count,
            }
            if registry.persistence is not None:
                from src.services.orchestration.scene import objectify_queue  # tránh vòng import

                # T-055: cùng một quy tắc "Tạo mesh lỗi" với danh sách scene và hàng tiến trình.
                request = objectify_queue.latest_request(registry.persistence.database, job.job_id)
                if objectify_queue.review_state(request, state, scene.scene_revision) == "failed":
                    result["object_geometry"]["state"] = "failed"
                if (
                    request is not None
                    and request.mode == "geometry"
                    and request.status == "done"
                    and request.result_revision == scene.scene_revision
                    and request.started_at is not None
                    and request.finished_at is not None
                ):
                    elapsed = (request.finished_at - request.started_at).total_seconds()
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


@lru_cache(maxsize=64)
def _redaction_summary(registry: ProjectRegistry, job_id: str, checksum: str) -> tuple[int, str, str]:
    from src.services.orchestration.jobs.anonymization_review import _load
    from src.services.orchestration.jobs.progress import sanitized_frame_stage

    job = registry.get_job(job_id)
    stage = sanitized_frame_stage(job)
    if stage is None or stage.artifact_checksum != checksum:
        raise ValueError("Bản đã che đã thay đổi trong khi đọc tiến trình")
    frames, manifest = _load(registry, job)
    return sum(len(frame.regions) for frame in manifest.frames), frames.frame_set_checksum, manifest.manifest_checksum


def stage_notes(registry: ProjectRegistry, job: JobManifest) -> dict[StageId, str]:
    """Một dòng tiếng Việt từ đúng receipt của job, không suy theo cấu hình yêu cầu."""
    from src.services.orchestration.jobs.progress import (
        anonymization_acceptance_stage,
        awaiting_anonymization_review,
        sanitized_frame_stage,
    )

    result = recorded_results(registry, job)
    notes: dict[StageId, str] = {}
    metric = result.get("metric")
    if metric:
        source = metric["source"]
        label = {
            "user_measured": "Bạn đo tay",
            "ai_estimated": "Tỉ lệ máy đề xuất từ ảnh, bạn đã chấp nhận",
            "lidar_trajectory": "Tỉ lệ máy đề xuất từ LiDAR, bạn đã chấp nhận",
            "lidar_demo": "Tỉ lệ đo từ LiDAR, bạn đã chấp nhận",
        }.get(source)
        if label:
            notes[StageId.METRIC_CANONICALIZE] = label
    if result.get("collision_source"):
        notes[StageId.RGB_GEOMETRY] = f"Lưới từ {result['collision_source']}"
    if "candidate_count" in result:
        notes[StageId.OBJECT_EXTRACT] = f"{result['candidate_count']} vật ứng viên"
    sanitized = sanitized_frame_stage(job)
    if sanitized is not None:
        try:
            count, frame_checksum, manifest_checksum = _redaction_summary(
                registry, job.job_id, sanitized.artifact_checksum
            )
            acceptance = anonymization_acceptance_stage(job)
            if acceptance and acceptance.artifact_uri and acceptance.artifact_checksum:
                record = _read(registry.runtime_resolver, acceptance.artifact_uri, acceptance.artifact_checksum)
                if (
                    record["frame_set_checksum"] == frame_checksum
                    and record["sanitization_manifest_checksum"] == manifest_checksum
                ):
                    notes[StageId.FRAME_EXTRACT] = (
                        f"Đã che {count} vùng (mặt, biển số); bạn đã chấp nhận"
                        if count
                        else "Không có vùng cần che; hệ thống đã kiểm tra"
                    )
            elif awaiting_anonymization_review(job):
                notes[StageId.FRAME_EXTRACT] = f"Chờ bạn duyệt {count} vùng đã che"
        except (ArtifactStoreError, OSError, ValueError, KeyError, TypeError) as error:
            logger.debug("Không có receipt che hợp lệ cho %s: %s", job.job_id, error)
    return notes


def geometry_surface_note(objects: list[Any]) -> str | None:
    """Chỉ đếm vật có QA lựa chọn bề mặt, không coi dữ liệu thiếu là vỏ cũ."""
    chosen = [(item.provenance.get("surface_selection") or {}).get("chosen") for item in objects]
    if not any(value in {"objectgs", "gaussian_shell"} for value in chosen):
        return None
    return f"{chosen.count('objectgs')} vật dùng bề mặt ObjectGS; {chosen.count('gaussian_shell')} vật dùng cách cũ (vỏ Gaussian)"
