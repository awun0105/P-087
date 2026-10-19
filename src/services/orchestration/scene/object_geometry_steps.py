"""Reusable geometry stages for object extraction and builds from reviewed membership."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import numpy as np
import trimesh

from src.config import Settings
from src.models.contracts.artifacts import JsonObject, ProductArtifactRef
from src.models.contracts.floor_model import FloorModel
from src.models.contracts.manifests import StageId
from src.models.contracts.object_geometry import ObjectAwareEnvironmentManifest
from src.models.contracts.object_membership import ObjectMembershipArtifact
from src.models.contracts.reconstruction import ReconstructionBundle

Publish = Callable[[ProductArtifactRef, bytes], ProductArtifactRef]


def build_environment_collision(
    *,
    source_points: np.ndarray,
    membership_labels: np.ndarray,
    label_to_object_id: dict[str, str],
    footprints: list[tuple[np.ndarray, np.ndarray]],
    floor_model: FloorModel,
    floor_fit: JsonObject,
    voxel_m: float,
    bundle: ReconstructionBundle,
    membership: ObjectMembershipArtifact,
    publish: Publish,
    job_id: str,
    footprint_centers: list[tuple[float, float, float]] | None = None,
) -> tuple[ProductArtifactRef, ProductArtifactRef]:
    """Publish source-world background collision with inferred support under source footprints.

    Corrections can retain an off-centre source pose; footprint_centers preserves its contact check.
    """
    # Resolve shared execution primitives at call time; objectify also calls these geometry stages.
    from src.services.orchestration.scene.objectify import ObjectifyError, _reference, build_background_collision

    support = []
    # Inferred support never comes from inpaint rows or a current edited object pose.
    if floor_model.status in {"supported", "confirmed_prior_fallback"}:
        normal = np.asarray(floor_model.plane_normal_world)
        for index, (low, high) in enumerate(footprints):
            center = (low + high) / 2 if footprint_centers is None else footprint_centers[index]
            base = np.array([center[0], center[1], low[2]])
            if abs(float(normal @ base + floor_model.plane_offset_m)) > floor_model.floor_band_m + 2 * voxel_m:
                continue
            xs = np.arange(low[0], high[0] + voxel_m, voxel_m)
            ys = np.arange(low[1], high[1] + voxel_m, voxel_m)
            if len(xs) * len(ys) > 1_000_000:
                raise ObjectifyError("inferred support exceeds the geometry budget", retryable=False)
            for x in xs:
                for y in ys:
                    z = -(normal[0] * x + normal[1] * y + floor_model.plane_offset_m) / normal[2]
                    support.append([x, y, z])
    background_mesh = build_background_collision(
        source_points,
        membership_labels,
        {int(label) for label in label_to_object_id},
        voxel_m=voxel_m,
        unknown=membership_labels < 0,
        inferred_support_points=np.asarray(support).reshape(-1, 3),
    )
    mesh = trimesh.Trimesh(background_mesh.vertices, background_mesh.faces, process=False)
    collision_payload = mesh.export(file_type="glb")
    active_ref = publish(
        _reference(
            job_id,
            "objectgs/environment/{digest}.glb",
            "ObjectAwareEnvironmentCollision",
            StageId.COLLIDER,
            collision_payload,
        ),
        collision_payload,
    )
    manifest = ObjectAwareEnvironmentManifest(
        source_geometry_ref=bundle.canonical_geometry_ref,
        collision_ref=active_ref,
        source_membership=membership,
        removed_object_ids=sorted(label_to_object_id.values()),
        occupancy_checksum=background_mesh.occupancy_checksum,
        provenance={
            "statistics": background_mesh.statistics,
            "voxel_m": voxel_m,
            "support_origin": "inferred_floor_plane_under_source_contact_footprints",
            "floor_fit": floor_fit,
            "watertight": bool(mesh.is_watertight),
            "inpaint_used_for_physics": False,
        },
    )
    manifest_payload = manifest.model_dump_json().encode()
    manifest_ref = publish(
        _reference(
            job_id,
            "objectgs/environment/{digest}.json",
            "ObjectAwareEnvironmentManifest",
            StageId.COLLIDER,
            manifest_payload,
        ),
        manifest_payload,
    )
    return active_ref, manifest_ref


@dataclass(frozen=True)
class SurfaceInput:
    """Strict object-local surface input, in metres, for a single convex-runner key."""

    key: str
    surface_path: Path
    surface_checksum: str
    output_glb: Path


def run_surface_colliders(
    python: Path,
    inputs: list[SurfaceInput],
    coacd_config: dict,
    workspace: Path,
    timeout: float,
    cancel_event: Event | None,
    *,
    surface_label: str = "ObjectGS surface",
    surface_origin: str = "objectgs",
) -> dict[str, dict]:
    """Run strict surface CoACD and reject missing, failed or empty collider output."""
    from src.services.orchestration.scene.objectify import CONVEX_RUNNER, ObjectifyError, _run

    request = {
        "objects": [
            {
                "id": item.key,
                "surface_mesh": str(item.surface_path),
                "surface_checksum": item.surface_checksum,
                "surface_origin": surface_origin,
                "coordinate_frame": "object_local",
                "distance_unit": "m",
                "output_glb": str(item.output_glb),
            }
            for item in inputs
        ],
        "config": coacd_config,
    }
    result = _run(python, CONVEX_RUNNER, request, workspace, "convex", timeout, cancel_event=cancel_event)
    colliders = {str(item["id"]): item for item in result["objects"]}
    failures: dict[str, list[str]] = {}
    for item in inputs:
        entry = colliders.get(item.key)
        if entry is None:
            reason = "không có kết quả tạo collider"
        elif entry.get("error"):
            reason = str(entry["error"])
        elif not entry.get("parts"):
            reason = "không tạo được khối lồi nào"
        elif not item.output_glb.is_file():
            reason = "thiếu file collider đầu ra"
        else:
            continue
        if "intersection_budget_exceeded" in reason:
            reason = "chưa hoàn tất kiểm tra giao cắt"
        elif "surface parts exceed budget" in reason or "disconnected components but the object hull budget" in reason:
            reason = "số phần rời vượt giới hạn khối lồi của vật"
        elif "exceeded the part budget" in reason:
            reason = "không tạo được khối lồi trong giới hạn đã cấp"
        failures.setdefault(reason, []).append(item.key)
    if failures:
        details = "; ".join(f"{', '.join(keys)}: {reason}" for reason, keys in failures.items())
        raise ObjectifyError(
            f"{surface_label} collider generation failed; Gaussian/OBB fallback is forbidden. " + details,
            retryable=False,
        )
    return colliders


def run_inpaint(
    python: Path,
    *,
    background_ply: Path,
    objects_ply: Path,
    views: list[dict],
    settings: Settings,
    inpaint_config: dict,
    workspace: Path,
    timeout: float,
    cancel_event: Event | None,
) -> dict:
    """Run only inpaint so extraction can wait for CoACD before packaging and publication."""
    from src.services.orchestration.scene.objectify import INPAINT_RUNNER, _run

    inpaint_request = {
        "background_ply": str(background_ply),
        "objects_ply": str(objects_ply),
        "output_ply": str(workspace / "background_inpainted.ply"),
        "lama_checkpoint": str(settings.product_lama_checkpoint) if settings.product_lama_checkpoint else None,
        "views": views,
        "config": inpaint_config,
    }
    return _run(python, INPAINT_RUNNER, inpaint_request, workspace, "inpaint", timeout, cancel_event=cancel_event)


def run_inpaint_and_package(
    python: Path,
    *,
    background_ply: Path,
    objects_ply: Path,
    views: list[dict],
    settings: Settings,
    inpaint_config: dict,
    workspace: Path,
    timeout: float,
    cancel_event: Event | None,
    publish: Publish,
    job_id: str,
    inpaint_result: dict | None = None,
    before_publish: Callable[[], None] | None = None,
) -> tuple[ProductArtifactRef, ProductArtifactRef, dict]:
    """Inpaint, package SOG and publish background artifacts using the existing content paths.

    Extraction supplies its parallel inpaint result and publishes membership after packaging succeeds.
    """
    from src.services.orchestration.scene.objectify import (
        ObjectifyError,
        _ensure_not_cancelled,
        _reference,
        package_splat,
    )

    if inpaint_result is None:
        inpaint_result = run_inpaint(
            python,
            background_ply=background_ply,
            objects_ply=objects_ply,
            views=views,
            settings=settings,
            inpaint_config=inpaint_config,
            workspace=workspace,
            timeout=timeout,
            cancel_event=cancel_event,
        )
    try:
        sog = package_splat(
            workspace / "background_inpainted.ply",
            workspace / "sog",
            settings.product_geometry_gpu_index,
            cancel_event=cancel_event,
        )
    except (ValueError, OSError) as error:
        raise ObjectifyError(f"nén SOG nền lỗi: {error}") from error

    if before_publish is not None:
        before_publish()
    _ensure_not_cancelled(cancel_event)
    background_payload = (workspace / "background_inpainted.ply").read_bytes()
    master_ref = publish(
        _reference(
            job_id, "environment/{digest}/background.ply", "GaussianPLY", StageId.SCENE_DECOMPOSE, background_payload
        ),
        background_payload,
    )
    sog_payload = sog.read_bytes()
    visual_ref = publish(
        _reference(
            job_id, "environment/{digest}/background.sog", "VisualArtifact", StageId.SCENE_DECOMPOSE, sog_payload
        ),
        sog_payload,
    )

    return master_ref, visual_ref, inpaint_result
