"""Tạo gói mô phỏng cho Isaac từ SceneIR hiện tại (nối EX-SIM SIM-02/03/04/05 vào luồng Studio).

1. Môi trường: collision mesh REC-05 của scene, bỏ source region theo ownership bất biến của
   object được xác nhận/đã xoá, ghi thành layer USD Mesh tĩnh; sàn là ground plane.
2. Vật: collider theo ColliderSpec, đúng hình học/kích thước và frame cục bộ.
3. Preflight tĩnh (SIM-04) trên đúng revision sẽ đóng gói; FAIL thì trả báo cáo, không tạo
   revision mới.
4. Static Preflight PASS + export capability SUPPORTED: publish revision SceneIR có collider,
   đóng gói CandidatePackage (SIM-05) và một file zip tải về. Bản ghi gói khoá theo revision.

Scene theo vật (pipeline v2, ADR 0007): entrypoint **USD lai** do `usd/hybrid_runner.py` dựng trong
runtime có usd-core. Builder giữ Gaussian, collider AABB/OBB hoặc các mảnh lồi, local transform,
ObjectPhysics đã lưu và USD assets đã checksum-verify rồi đóng gói bằng reference tương đối. Ứng viên
chưa xác nhận vẫn là một phần hình của nền; vật đã loại/xoá/ẩn không xuất. Các layer nằm trong inventory.

Physics trong Isaac (SIM-06+) chạy ở máy RTX, ngoài phạm vi bước này.
"""

import hashlib
import io
import json
import logging
import subprocess
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict, Field

from src.config import get_settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.collision_quality import (
    CollisionInputMode,
    CollisionSourceMode,
    CollisionSourceSelection,
)
from src.models.contracts.manifests import StageId
from src.models.contracts.scene import (
    ColliderType,
    SceneIR,
    SceneObject,
    SceneObjectOrigin,
    SceneObjectState,
    SourceCollisionRegion,
)
from src.models.contracts.validation import CandidatePackage, PreflightReport, RuleResult
from src.services.orchestration.artifacts.errors import ArtifactStoreError
from src.services.orchestration.processing.config import job_config_reference
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.reconstruction.adapters.lidar_collision import LidarCollisionBuildReport
from src.services.reconstruction.lidar.collision_candidate_publisher import (
    LidarCollisionCandidateManifest,
    load_lidar_collision_eligibility_inputs,
)
from src.services.reconstruction.lidar.collision_eligibility import evaluate_lidar_collision_eligibility
from src.services.scene.collision_ownership import (
    SourceCollisionOwnershipError,
    bind_source_collision_ownership,
    read_triangle_memberships,
)
from src.services.simulation.colliders.carve import (
    COLLISION_CARVE_MARGIN_M,
    CarveBox,
    carve_triangle_mask,
    triangle_mask_in_box,
)
from src.services.simulation.enrichment.service import enrich_scene_physics
from src.services.simulation.preflight.engine import run_preflight
from src.services.simulation.usd.builder import (
    CandidateBuildRequest,
    _compute_config_checksum,
    build_candidate_package,
)
from src.services.simulation.usd.capabilities import (
    EffectiveExportMode,
    ExportCapabilityBlocker,
    ExportCapabilityReport,
    ExportCapabilityStatus,
    ExportRequirements,
    RuntimeQualificationStatus,
    assess_export_capabilities,
    catalog_asset_provenance,
    export_requirements,
    select_export_mode,
)
from src.services.simulation.usd.physics_config import physics_build_config
from src.services.simulation.usd.usda import generate_mesh_layer_usda, generate_scene_usda

logger = logging.getLogger(__name__)

ENVIRONMENT_LAYER = "environment_collision.usda"
BUILD_CONFIG = {
    **physics_build_config({}),
    "builder": "real2sim-studio-simulation-package-v6-physics-config",
    "capability_contract": "usd-export-capabilities-v2",
    "requested_mode": "auto",
    "effective_mode": "legacy_box",
    "runtime_usd_version": None,
    "environment": "rec05_collision_mesh_source_owned_triangle_mesh",
    "carve_margin_m": COLLISION_CARVE_MARGIN_M,
    "background_identity_algorithm": "source_geometry_checksum+removed_triangle_mask_v1",
    "ground_plane": True,
    "object_collider": "exact_box_collider_dimensions_and_local_transform",
}
HYBRID_BUILD_CONFIG = {
    **physics_build_config({}),
    "builder": "real2sim-studio-simulation-package-v6-physics-config-hybrid",
    "capability_contract": "usd-export-capabilities-v2",
    "requested_mode": "auto",
    "effective_mode": "hybrid",
    "runtime_probe": "hybrid-runner-probe-v2",
    "runtime_usd_version": None,
    "environment": "inpainted_gaussians_particlefield+rec05_source_owned_collision_mesh",
    "carve_margin_m": COLLISION_CARVE_MARGIN_M,
    "background_identity_algorithm": "source_geometry_checksum+removed_triangle_mask_v1",
    "ground_plane": True,
    "object_visual": "per_object_gaussians_particlefield",
    "object_collider": "exact_aabb_obb_local_transform_or_validated_convex_parts",
    "object_asset": "checksum_sealed_usd_asset_relative_reference",
    "object_physics": "authored_object_physics_with_global_material_fallback",
}
HYBRID_RUNNER = Path(__file__).resolve().parents[3] / "services/simulation/usd/hybrid_runner.py"


@dataclass(frozen=True)
class CarvedBackground:
    """Verified source collision mesh shared by all package builders."""

    vertices: np.ndarray
    faces: np.ndarray
    carved_triangles: int
    identity: str
    #: Triangles claimed by both a carved and a kept source region; they stay in the background.
    retained_shared_triangles: int = 0
    #: Kept objects whose region shares triangles with a carved one (the user can resolve them).
    retained_shared_object_ids: tuple[str, ...] = ()


class SimulationPackage(BaseModel):
    """Kết quả build; `package_ref` chỉ có khi preflight và export capability đều đạt."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    source_scene_revision: str
    scene_revision: str
    scene_ir_checksum: str
    created_at: datetime
    preflight: PreflightReport
    confirmed_objects: int
    environment_triangles: int
    carved_triangles: int
    #: Background triangles kept because an approximate source box is shared with an object that stays.
    retained_shared_triangles: int = 0
    retained_shared_object_ids: list[str] = Field(default_factory=list)
    export_capability: ExportCapabilityReport | None = None
    candidate: CandidatePackage | None = None
    package_ref: ProductArtifactRef | None = None


def record_uri(job_id: str, scene_revision: str) -> str:
    """Bản ghi gói của đúng revision (bất biến; revision mới → bản ghi mới)."""
    return f"artifact://jobs/{job_id}/simulation/{scene_revision}.json"


def _reference(job_id: str, uri_tail: str, artifact_type: str, stage: StageId, payload: bytes) -> ProductArtifactRef:
    digest = hashlib.sha256(payload).hexdigest()
    return ProductArtifactRef(
        artifact_type=artifact_type,
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{job_id}/simulation/{digest}/{uri_tail}",
        artifact_checksum=f"sha256:{digest}",
        data_class=ArtifactDataClass.DERIVED,
        producer_stage=stage,
        job_id=job_id,
    )


def _publish(registry: ProjectRegistry, reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
    """Publish idempotent: cùng nội dung → cùng URI, đã có thì dùng lại."""
    if registry.runtime_resolver.locate(reference.artifact_uri) is not None:
        return reference
    return registry.scene.store.publish(reference, payload)


def _job_simulation_config(registry: ProjectRegistry, job_id: str) -> dict[str, bool | float]:
    """Read checksum-bound job controls; legacy jobs without an artifact retain defaults."""
    job = registry.get_job(job_id)
    reference = job_config_reference(job_id, job.config_checksum)
    if registry.runtime_resolver.locate(reference.artifact_uri) is None:
        return physics_build_config({})
    payload = json.loads(registry.runtime_resolver.require(reference).read_bytes())
    values = payload.get("simulation", {})
    if not isinstance(values, dict):
        raise ValueError("job simulation config must be an object")
    return physics_build_config(values)


def current_package(
    registry: ProjectRegistry, job_id: str, *, simulation_config: dict[str, object] | None = None
) -> SimulationPackage | None:
    """Gói của revision SceneIR hiện tại, nếu đã tạo."""
    scene = registry.scene.current(job_id).scene
    controls = (
        _job_simulation_config(registry, job_id)
        if simulation_config is None
        else physics_build_config(simulation_config)
    )
    path = registry.runtime_resolver.locate(record_uri(job_id, scene.scene_revision))
    if path is None:
        return None
    package = SimulationPackage.model_validate_json(path.read_bytes())
    capability = package.export_capability
    background_identity = scene.provenance.get("collision_background_identity")
    if capability is None or not isinstance(background_identity, str):
        return None
    mode = select_export_mode(export_requirements(scene))
    build_config = _package_build_config(
        mode,
        background_identity,
        capability.runtime_version if mode == EffectiveExportMode.HYBRID else None,
        controls,
    )
    return package if _cache_matches(package, scene, build_config, export_requirements(scene)) else None


def _source_region_removed(item: SceneObject, objects_by_id: dict[str, SceneObject]) -> bool:
    """Whether this immutable source region leaves the background after review/merge."""
    visited: set[str] = set()
    while item.provenance.get("review") == "MERGED":
        if item.id in visited:
            return False
        visited.add(item.id)
        merged_into = item.provenance.get("merged_into")
        if not isinstance(merged_into, str) or merged_into not in objects_by_id:
            return False
        item = objects_by_id[merged_into]
    if item.provenance.get("duplicated_from") is not None:
        return False
    review = item.provenance.get("review")
    return review == "DELETED" or (review != "IGNORED" and item.state == SceneObjectState.CONFIRMED)


#: Operations that replace the whole reconstructed object set. Their revision still holds each object at
#: the pose it was extracted with, so it is the original artifact ownership can be recovered from.
_EXTRACTION_OPERATIONS = frozenset({"objectify", "use_boxes"})


def _recover_legacy_source_ownership(
    registry: ProjectRegistry, job_id: str, scene: SceneIR
) -> tuple[SceneIR, dict[str, str]]:
    """Recover omitted ownership without ever using an edited pose.

    1. An earlier checksum-validated revision of the same object (same id and geometry artifact) that
       already carries ownership wins.
    2. Otherwise the object's unbroken run of revisions must start at an extraction output: the root
       revision, or the first revision of a re-extraction. That revision still has the pose the object
       was extracted with, which is exactly what `bind_source_collision_ownership` records.
    Anything else stays unrecovered and the carve fails closed.
    """
    current_objects = {item.id: item for item in scene.objects}
    # A duplicate never owns a source region, so it must not send recovery through the whole history.
    missing = {
        item.id
        for item in scene.objects
        if item.origin == SceneObjectOrigin.RECONSTRUCTED
        and item.source_collision is None
        and item.provenance.get("duplicated_from") is None
    }
    selected_source_ref = scene.environment.collision_source_ref
    if selected_source_ref is not None:
        incomplete = [
            item.id
            for item in scene.objects
            if item.origin == SceneObjectOrigin.RECONSTRUCTED
            and item.provenance.get("duplicated_from") is None
            and (
                item.source_collision is None
                or item.source_collision.source_geometry_ref != selected_source_ref
                or item.source_collision.region_kind != "triangle_indices"
            )
        ]
        if incomplete:
            raise SourceCollisionOwnershipError(
                "selected collision source cannot recover ownership from RGB history; remap exact LiDAR regions for: "
                + ", ".join(sorted(incomplete))
            )
        return scene, {}
    if not missing:
        return scene, {}

    recovered: dict[str, tuple[SourceCollisionRegion, str]] = {}
    run_start: dict[str, SceneIR] = {object_id: scene for object_id in missing}
    open_runs, introduced = set(missing), set[str]()
    seen = {scene.scene_revision}
    cursor = scene
    while missing:
        # A restore republishes the objects of `restored_from` verbatim, so their history continues there
        # rather than in the revision that happened to be current when the restore was requested.
        restored_from = cursor.provenance.get("restored_from")
        previous_revision = restored_from if cursor.provenance.get("operation") == "restore_revision" else None
        if not isinstance(previous_revision, str):
            previous_revision = cursor.provenance.get("edited_from")
        if not isinstance(previous_revision, str):
            previous_revision = cursor.provenance.get("previous_revision")
        if not isinstance(previous_revision, str) or previous_revision in seen:
            break
        seen.add(previous_revision)
        prior_record = registry.scene.revision(job_id, previous_revision)
        if prior_record is None:
            break
        prior = prior_record.scene
        if prior.scene_id != scene.scene_id or prior.environment.geometry_ref != scene.environment.geometry_ref:
            break
        prior_objects = {item.id: item for item in prior.objects}
        for object_id in tuple(missing):
            prior_object = prior_objects.get(object_id)
            # A re-extraction reuses ids (candidate-001...) for different objects; only the same
            # immutable geometry artifact proves an earlier revision describes this object.
            same_object = (
                prior_object is not None
                and prior_object.origin == SceneObjectOrigin.RECONSTRUCTED
                and prior_object.geometry_ref == current_objects[object_id].geometry_ref
            )
            owner = prior_object.source_collision if same_object and prior_object is not None else None
            if (
                owner is not None
                and owner.object_id == object_id
                and owner.source_geometry_ref == scene.environment.geometry_ref
            ):
                recovered[object_id] = owner, previous_revision
                missing.remove(object_id)
            elif object_id in open_runs:
                if same_object:
                    run_start[object_id] = prior
                else:
                    open_runs.discard(object_id)
                    introduced.add(object_id)
        cursor = prior

    for object_id in tuple(missing):
        start = run_start[object_id]
        is_root = start.provenance.get("edited_from") is None and start.provenance.get("previous_revision") is None
        extracted_here = object_id in introduced and start.provenance.get("operation") in _EXTRACTION_OPERATIONS
        if not (is_root or extracted_here) or start.environment.geometry_ref != scene.environment.geometry_ref:
            continue
        start_object = next(item for item in start.objects if item.id == object_id)
        try:
            (bound,) = bind_source_collision_ownership(
                [start_object], start.environment.geometry_ref, start.scene_revision
            )
        except ValueError:
            continue
        if bound.source_collision is not None:
            recovered[object_id] = bound.source_collision, start.scene_revision

    if not recovered:
        return scene, {}
    owners = {object_id: entry[0] for object_id, entry in recovered.items()}
    recovery_sources = {object_id: entry[1] for object_id, entry in sorted(recovered.items())}
    objects = [
        item.model_copy(update={"source_collision": owners[item.id]}, deep=True) if item.id in owners else item
        for item in scene.objects
    ]
    recovered_scene = scene.model_copy(
        update={
            "objects": objects,
            "provenance": {
                **scene.provenance,
                "source_collision_ownership_recovered": recovery_sources,
            },
        },
        deep=True,
    )
    return recovered_scene, recovery_sources


def _selected_collision_source(registry: ProjectRegistry, scene: SceneIR) -> tuple[ProductArtifactRef, bytes]:
    """Resolve and revalidate a selected sensor-package candidate before any export use."""
    environment = scene.environment
    source_ref = environment.collision_source_ref
    selection_ref = environment.collision_selection_ref
    if source_ref is None and selection_ref is None:
        return environment.geometry_ref, registry.runtime_resolver.require(environment.geometry_ref).read_bytes()
    if source_ref is None or selection_ref is None:
        raise SourceCollisionOwnershipError("selected collision source refs are incomplete; refusing RGB fallback")

    try:
        selection = CollisionSourceSelection.model_validate_json(
            registry.runtime_resolver.require(selection_ref).read_bytes()
        )
        if (
            selection.mode != CollisionSourceMode.LIDAR_DERIVED
            or selection.input_mode != CollisionInputMode.LIDAR_SENSOR_PACKAGE
            or selection.output_collision_ref != source_ref
            or selection.source_qa_ref.artifact_type != "LidarCalibrationQAReport"
            or selection.alignment_qa_ref is None
            or selection.alignment_qa_ref.artifact_type != "LidarCalibrationProjectionEvidence"
        ):
            raise ValueError("selection mode, QA, or output does not match the selected LiDAR source")
        raw_manifest_ref = selection_ref.source_provenance.get("candidate_manifest_ref")
        if not isinstance(raw_manifest_ref, dict):
            raise ValueError("selection ref does not bind a candidate manifest")
        manifest_ref = ProductArtifactRef.model_validate(raw_manifest_ref)
        if manifest_ref.artifact_type != "LidarCollisionCandidateManifest" or manifest_ref.job_id != source_ref.job_id:
            raise ValueError("candidate manifest ref belongs to another artifact contract or job")
        manifest = LidarCollisionCandidateManifest.model_validate_json(
            registry.runtime_resolver.require(manifest_ref).read_bytes()
        )
        evidence_refs = {reference.artifact_type: reference for reference in manifest.eligibility_evidence_refs}
        if (
            manifest.candidate_ref != source_ref
            or manifest.source_geometry_ref != selection.source_geometry_ref
            or evidence_refs.get("LidarCalibrationQAReport") != selection.source_qa_ref
            or evidence_refs.get("LidarCalibrationProjectionEvidence") != selection.alignment_qa_ref
            or manifest.profile_checksum != selection.profile_checksum
            or manifest.profile_checksum != selection.config_checksum
        ):
            raise ValueError("selection does not bind the manifest source, QA, profile, or output")
        eligibility_inputs = load_lidar_collision_eligibility_inputs(manifest, registry.runtime_resolver)
        eligibility = evaluate_lidar_collision_eligibility(eligibility_inputs)
        if eligibility.state != "eligible" or eligibility != manifest.eligibility:
            raise ValueError("candidate eligibility is no longer valid")
        report = LidarCollisionBuildReport.model_validate_json(
            registry.runtime_resolver.require(manifest.build_report_ref).read_bytes()
        )
        if (
            report.output_collision_checksum != manifest.output_collision_checksum
            or report.profile_checksum != manifest.profile_checksum
            or report.profile_id != manifest.profile.profile_id
            or report.voxel_m != manifest.profile.voxel_m
            or report.source_point_checksum != manifest.source_point_checksum
            or report.self_mask_evidence_ref != manifest.self_mask_evidence_ref
            or report.self_mask_binding_checksum != manifest.self_mask_binding_checksum
        ):
            raise ValueError("candidate build report differs from its immutable manifest")
        return source_ref, registry.runtime_resolver.require(source_ref).read_bytes()
    except (ArtifactStoreError, TypeError, ValueError) as error:
        raise SourceCollisionOwnershipError(
            f"selected LiDAR source could not be revalidated; refusing to fall back to canonical RGB geometry: {error}"
        ) from error


def _carved_environment(
    registry: ProjectRegistry, scene: SceneIR, *, margin_m: float = COLLISION_CARVE_MARGIN_M
) -> CarvedBackground:
    """Resolve the selected collision source; edited object transforms never define carve regions."""
    source_ref, glb = _selected_collision_source(registry, scene)
    margin_m = physics_build_config({"carve_margin_m": margin_m})["carve_margin_m"]
    source_checksum = f"sha256:{hashlib.sha256(glb).hexdigest()}"
    if source_checksum != source_ref.artifact_checksum:
        raise SourceCollisionOwnershipError("source collision bytes differ from selected geometry checksum")

    mesh = trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh", process=False)
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces)
    if not len(faces):
        raise SourceCollisionOwnershipError("source collision mesh has no triangles")

    reconstructed = [item for item in scene.objects if item.origin == SceneObjectOrigin.RECONSTRUCTED]
    objects_by_id = {item.id: item for item in reconstructed}
    selected_source = scene.environment.collision_source_ref is not None
    missing = [
        item.id
        for item in reconstructed
        if item.provenance.get("duplicated_from") is None
        and (
            (
                selected_source
                and (
                    item.source_collision is None
                    or item.source_collision.source_geometry_ref != source_ref
                    or item.source_collision.region_kind != "triangle_indices"
                )
            )
            or (not selected_source and _source_region_removed(item, objects_by_id) and item.source_collision is None)
        )
    ]
    if missing:
        ids = ", ".join(sorted(missing))
        raise SourceCollisionOwnershipError(
            f"reconstructed objects require source collision ownership before rebuilding background: {ids}"
        )

    owned = sorted((item for item in reconstructed if item.source_collision is not None), key=lambda item: item.id)
    source_owners = [item.source_collision for item in owned]
    if any(owner is None for owner in source_owners):  # narrowed below for static type checkers
        raise SourceCollisionOwnershipError("source collision ownership is incomplete")
    owners = [owner for owner in source_owners if owner is not None]
    for item, owner in zip(owned, owners, strict=True):
        if owner.object_id != item.id or owner.source_geometry_ref != source_ref:
            raise SourceCollisionOwnershipError(
                f"{item.id}: source collision ownership is not bound to this environment"
            )

    exact_owners = [owner for owner in owners if owner.region_kind == "triangle_indices"]
    memberships = read_triangle_memberships(
        exact_owners,
        glb,
        len(faces),
        lambda reference: registry.runtime_resolver.require(reference).read_bytes(),
    )

    centroids = vertices[faces].mean(axis=1)
    triangle_count = len(faces)
    regions: list[tuple[SceneObject, np.ndarray, bool]] = []
    exact_claim = np.zeros(triangle_count, dtype=bool)
    for item, owner in zip(owned, owners, strict=True):
        if owner.region_kind == "triangle_indices":
            indices = np.asarray(memberships[owner.object_id], dtype=np.intp)
            exact_claim[indices] = True
            regions.append((item, indices, True))
            continue
        dimensions = owner.source_obb_dimensions_xyz_m
        if dimensions is None:
            raise SourceCollisionOwnershipError(f"{owner.object_id}: source OBB dimensions are missing")
        box = CarveBox.from_transform(owner.source_transform, dimensions)
        indices = np.flatnonzero(triangle_mask_in_box(centroids, box, margin_m))
        regions.append((item, indices, False))

    carve_claim = np.zeros(triangle_count, dtype=bool)
    keep_claim = np.zeros(triangle_count, dtype=bool)
    kept_regions: list[tuple[str, np.ndarray]] = []
    for item, indices, exact in regions:
        if not exact:
            # Exact triangle membership is authoritative: an approximate box never takes a triangle from it.
            indices = indices[~exact_claim[indices]]
        if _source_region_removed(item, objects_by_id):
            carve_claim[indices] = True
        else:
            keep_claim[indices] = True
            kept_regions.append((item.id, indices))
    # Whoever owns a triangle claimed only by carved regions (or only by kept ones), the result is the same.
    # A triangle shared by a carved box and a kept box cannot be attributed: carving it could delete collision
    # of an object that stays, keeping it leaves at most that shared sliver. Keep it, never guess, and report it.
    shared = carve_claim & keep_claim
    remove_mask = carve_claim & ~keep_claim
    shared_object_ids = tuple(sorted(object_id for object_id, indices in kept_regions if shared[indices].any()))

    background_hash = hashlib.sha256()
    identity_header = json.dumps(
        {
            "algorithm": "source_geometry_checksum+removed_triangle_mask_v1",
            "source_geometry_checksum": source_checksum,
            "source_triangle_count": len(faces),
            "carve_margin_m": margin_m,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    background_hash.update(identity_header)
    background_hash.update(np.packbits(remove_mask, bitorder="little").tobytes())
    carved_vertices, carved_faces, carved = carve_triangle_mask(vertices, faces, remove_mask)
    return CarvedBackground(
        carved_vertices,
        carved_faces,
        carved,
        f"sha256:{background_hash.hexdigest()}",
        retained_shared_triangles=int(np.count_nonzero(shared)),
        retained_shared_object_ids=shared_object_ids,
    )


def _prim_name(object_id: str) -> str:
    return "".join(char if char.isalnum() or char == "_" else "_" for char in object_id)


def _is_pending(item: SceneObject) -> bool:
    """Ứng viên chưa được xác nhận/loại/xoá: vẫn là một phần hình của nền khi xuất."""
    return item.state == SceneObjectState.CANDIDATE and item.provenance.get("review") not in {
        "IGNORED",
        "DELETED",
        "MERGED",
    }


def _hybrid_layers(
    registry: ProjectRegistry,
    scene: SceneIR,
    output: Path,
    background: CarvedBackground,
    python: Path | None,
    *,
    simulation_config: dict[str, object] | None = None,
) -> dict[str, bytes] | None:
    """Dựng USD lai cho scene theo vật; None chỉ khi caller không chọn builder lai.

    Trả `{đường dẫn tương đối trong gói: bytes}` gồm `scene.usda`, `environment.usdc`, `objects/*.usdc`.
    """
    if python is None:
        return None
    if not python.is_file():
        raise ValueError("USD runtime disappeared after hybrid package selection")
    resolve = registry.runtime_resolver.require
    collision = output / "environment_collision.ply"
    trimesh.Trimesh(background.vertices, background.faces, process=False).export(collision)
    objects, extra = [], []
    for item in scene.objects:
        if not item.active:
            continue
        gaussians = item.visual_ref if item.visual_ref and item.visual_ref.artifact_type == "ObjectGaussians" else None
        if _is_pending(item):
            if gaussians is not None:
                extra.append({"ply": str(resolve(gaussians)), "translation": list(item.transform.translation_xyz)})
            continue
        if not (item.active and item.state == SceneObjectState.CONFIRMED):
            continue
        collider = item.collider
        if collider is None:
            raise ValueError(f"confirmed object '{item.id}' has no collider for hybrid export")
        convex = collider.collider_type == ColliderType.CONVEX_DECOMPOSITION
        asset = item.asset_ref
        asset_suffix = PurePosixPath(asset.artifact_uri).suffix.lower() if asset is not None else None
        objects.append(
            {
                "prim": _prim_name(item.id),
                "name": item.name,
                "translation": list(item.transform.translation_xyz),
                "rotation_xyzw": list(item.transform.rotation_quaternion_xyzw),
                "gaussians_ply": str(resolve(gaussians)) if gaussians is not None else None,
                "collider": {
                    "type": collider.collider_type.value,
                    "geometry_path": str(resolve(collider.geometry_ref)) if convex and collider.geometry_ref else None,
                    "part_paths": [],
                    "dimensions_xyz_m": list(collider.dimensions_xyz_m) if collider.dimensions_xyz_m else None,
                    "local_transform": {
                        "translation_xyz": list(collider.local_transform.translation_xyz),
                        "rotation_quaternion_xyzw": list(collider.local_transform.rotation_quaternion_xyzw),
                    },
                },
                "semantic_class": item.semantic_class,
                "physics": item.physics.model_dump(mode="json") if item.physics is not None else None,
                "asset_source_path": str(resolve(asset)) if asset is not None else None,
                "asset_package_path": (
                    f"assets/{asset.artifact_checksum.removeprefix('sha256:')}{asset_suffix}"
                    if asset is not None and asset_suffix is not None
                    else None
                ),
                "asset_checksum": asset.artifact_checksum if asset is not None else None,
                "catalog": catalog_asset_provenance(item),
            }
        )
    request = {
        "output_dir": str(output / "hybrid"),
        **physics_build_config(simulation_config or {}),
        "collision_background_identity": background.identity,
        "environment": {
            "gaussians_ply": (
                str(resolve(scene.environment.visual_master_ref)) if scene.environment.visual_master_ref else None
            ),
            "extra_gaussians": extra,
            "collision_mesh": str(collision),
        },
        "objects": objects,
    }
    (output / "hybrid.request.json").write_text(json.dumps(request), encoding="utf-8")
    try:
        completed = subprocess.run(
            [
                str(python),
                str(HYBRID_RUNNER),
                "--request",
                str(output / "hybrid.request.json"),
                "--result",
                str(output / "hybrid.result.json"),
            ],
            capture_output=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError("xuất USD lai quá thời gian cho phép") from error
    if completed.returncode != 0:
        raise ValueError(f"xuất USD lai lỗi: {completed.stderr.decode(errors='replace')[-400:]}")
    result_path = output / "hybrid.result.json"
    try:
        summary = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("USD runner did not return a valid build summary") from error
    if not isinstance(summary, dict) or summary.get("root") != "scene.usda":
        raise ValueError("USD runner output does not identify the expected scene root")
    summary_objects = summary.get("objects")
    expected = {item["prim"]: item["collider"]["type"] for item in objects}
    if (
        not isinstance(summary_objects, list)
        or len(summary_objects) != len(expected)
        or any(not isinstance(item, dict) for item in summary_objects)
    ):
        raise ValueError("USD runner output has an invalid object summary")
    actual = {item.get("prim"): item.get("collider_type") for item in summary_objects}
    if actual != expected:
        raise ValueError("USD runner output does not cover the requested objects and collider types")
    expected_by_prim = {item["prim"]: item for item in objects}
    for item in summary_objects:
        requested = expected_by_prim[item["prim"]]
        collision_parts = item.get("collision_parts")
        if (
            isinstance(collision_parts, bool)
            or not isinstance(collision_parts, int)
            or collision_parts < 1
            or item.get("collider_local_transform") != requested["collider"]["local_transform"]
        ):
            raise ValueError("USD runner output did not preserve collider topology or local transforms")
        if item.get("catalog") != requested["catalog"]:
            raise ValueError("USD runner output did not preserve catalog asset provenance")
    expected_assets = [
        {"prim": item["prim"], "path": item["asset_package_path"], "checksum": item["asset_checksum"]}
        for item in objects
        if item["asset_package_path"] is not None
    ]
    if summary.get("external_assets") != expected_assets:
        raise ValueError("USD runner output does not match the resolved asset closure")
    root = output / "hybrid"
    (root / "usd_export_summary.json").write_text(
        json.dumps(summary, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _environment_layer(
    registry: ProjectRegistry, job_id: str, background: CarvedBackground
) -> tuple[ProductArtifactRef, int, int]:
    """Layer USD collider từ source-owned background; trả (ref, tam giác còn lại, tam giác bỏ)."""
    payload = generate_mesh_layer_usda(background.vertices, background.faces).encode("utf-8")
    reference = _reference(job_id, ENVIRONMENT_LAYER, "ColliderGeometry", StageId.COLLIDER, payload)
    return _publish(registry, reference, payload), int(len(background.faces)), background.carved_triangles


def _hybrid_runtime_python() -> Path | None:
    """Return the configured interpreter path; qualification is a separate subprocess probe."""
    python = get_settings().product_scene_runtime_python
    if python is None or not python.is_file():
        return None
    return python


def _qualify_hybrid_runtime(python: Path | None) -> tuple[bool, str | None]:
    """Verify the configured interpreter can exercise the actual USD APIs the runner uses."""
    if python is None or not python.is_file() or not HYBRID_RUNNER.is_file():
        return False, None
    with tempfile.TemporaryDirectory(prefix="r2s_usd_probe_") as directory:
        result_path = Path(directory) / "probe.json"
        try:
            completed = subprocess.run(
                [str(python), str(HYBRID_RUNNER), "--probe", "--result", str(result_path)],
                capture_output=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False, None
        if completed.returncode != 0 or not result_path.is_file():
            return False, None
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, None
    if not isinstance(result, dict):
        return False, None
    required = {
        "triangle_mesh_collision",
        "convex_mesh_collision",
        "rigid_body_mass",
        "physics_material",
        "collider_local_transform",
        "physics_source_metadata",
        "semantic_labels",
        "gaussian_particle_field",
        "meters_z_up",
    }
    capabilities = result.get("capabilities")
    version = result.get("usd_version")
    if (
        result.get("qualified") is not True
        or not isinstance(capabilities, list)
        or not all(isinstance(capability, str) for capability in capabilities)
        or not required.issubset(capabilities)
        or not isinstance(version, str)
    ):
        return False, None
    return True, version


def _package_build_config(
    mode: EffectiveExportMode,
    background_identity: str,
    runtime_version: str | None,
    simulation_config: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Bind package identity to mode, builder/runtime contract, and carved source mesh."""
    base = HYBRID_BUILD_CONFIG if mode == EffectiveExportMode.HYBRID else BUILD_CONFIG
    return {
        **base,
        **physics_build_config(simulation_config or {}),
        "runtime_usd_version": runtime_version if mode == EffectiveExportMode.HYBRID else None,
        "collision_background_identity": background_identity,
    }


def _cache_matches(
    package: SimulationPackage | None,
    scene: SceneIR,
    build_config: dict[str, Any],
    requested_requirements: ExportRequirements,
) -> bool:
    """Reuse only a sealed package with exact SceneIR, builder version and requirements."""
    if package is None or package.candidate is None or package.package_ref is None:
        return False
    capability = package.export_capability
    if capability is None or capability.status != ExportCapabilityStatus.SUPPORTED:
        return False
    if capability.builder_version != "usd-export-capabilities-v2" or capability.blockers:
        return False
    if package.preflight.blocking_result != RuleResult.PASS:
        return False
    if capability.scene_revision != scene.scene_revision or capability.scene_ir_checksum != scene.scene_ir_checksum:
        return False
    if package.scene_revision != scene.scene_revision or package.scene_ir_checksum != scene.scene_ir_checksum:
        return False
    manifest = package.candidate.candidate_manifest
    if manifest.scene_revision != scene.scene_revision or manifest.scene_ir_checksum != scene.scene_ir_checksum:
        return False
    if capability.requirements != requested_requirements:
        return False
    if capability.effective_mode.value != build_config.get("effective_mode"):
        return False
    if capability.effective_mode == EffectiveExportMode.HYBRID and (
        capability.runtime_qualification != RuntimeQualificationStatus.QUALIFIED or not capability.runtime_version
    ):
        return False
    return manifest.build_config_checksum == _compute_config_checksum(build_config)


def build_simulation_package(
    registry: ProjectRegistry, job_id: str, *, simulation_config: dict[str, object] | None = None
) -> SimulationPackage:
    """Tạo (hoặc trả lại) gói mô phỏng của revision SceneIR hiện tại."""
    current = registry.scene.current(job_id)
    scene, recovered_ownership = _recover_legacy_source_ownership(registry, job_id, current.scene)
    job = registry.get_job(job_id)
    controls = (
        _job_simulation_config(registry, job_id)
        if simulation_config is None
        else physics_build_config(simulation_config)
    )
    background = _carved_environment(registry, scene, margin_m=controls["carve_margin_m"])

    # A cache hit is valid only for the exact requested mode, capability contract,
    # runtime version, source collision identity and current SceneIR requirements.
    existing = current_package(registry, job_id, simulation_config=controls)
    current_requirements = export_requirements(scene)
    current_mode = select_export_mode(current_requirements)
    cached_capability = existing.export_capability if existing is not None else None
    current_runtime_ok = (
        cached_capability is not None
        and cached_capability.runtime_qualification == RuntimeQualificationStatus.QUALIFIED
    )
    current_runtime_version = cached_capability.runtime_version if cached_capability is not None else None
    current_build_config = _package_build_config(current_mode, background.identity, current_runtime_version, controls)
    current_capability = assess_export_capabilities(
        scene,
        runtime_qualified=current_runtime_ok,
        runtime_version=current_runtime_version,
        resolve_artifact=registry.runtime_resolver.require,
    )
    if (
        not recovered_ownership
        and current_capability.status == ExportCapabilityStatus.SUPPORTED
        and _cache_matches(existing, scene, current_build_config, current_requirements)
    ):
        return existing

    # Prepare an in-memory revision first so generated box colliders are included
    # in the requirements. It is not published and does not create a scene revision.
    prepared = enrich_scene_physics(scene, environment_collider_ref=scene.environment.collider_ref)
    requirements = export_requirements(prepared)
    mode = select_export_mode(requirements)
    hybrid_python = _hybrid_runtime_python() if mode == EffectiveExportMode.HYBRID else None
    runtime_qualified, runtime_version = (
        _qualify_hybrid_runtime(hybrid_python) if mode == EffectiveExportMode.HYBRID else (False, None)
    )
    build_config = _package_build_config(mode, background.identity, runtime_version, controls)

    enriched = enrich_scene_physics(
        scene,
        environment_collider_ref=scene.environment.collider_ref,
        extra_provenance={
            "simulation_package": build_config["builder"],
            "collision_background_identity": background.identity,
        },
    )
    root = registry.runtime_resolver.artifact_root
    confirmed = sum(1 for item in scene.objects if item.active and item.state == SceneObjectState.CONFIRMED)
    export_capability = assess_export_capabilities(
        enriched,
        runtime_qualified=runtime_qualified,
        runtime_version=runtime_version,
        resolve_artifact=registry.runtime_resolver.require,
    )
    if export_capability.status == ExportCapabilityStatus.BLOCKED:
        # Static preflight and exporter support are separate results. No candidate
        # or physics_enrich revision is published for an unsupported capability.
        return SimulationPackage(
            job_id=job_id,
            source_scene_revision=scene.scene_revision,
            scene_revision=enriched.scene_revision,
            scene_ir_checksum=enriched.scene_ir_checksum,
            created_at=datetime.now(UTC),
            preflight=run_preflight(enriched),
            confirmed_objects=confirmed,
            environment_triangles=len(background.faces),
            carved_triangles=background.carved_triangles,
            retained_shared_triangles=background.retained_shared_triangles,
            retained_shared_object_ids=list(background.retained_shared_object_ids),
            export_capability=export_capability,
        )

    layer_ref, triangles, carved = _environment_layer(registry, job_id, background)
    enriched = enrich_scene_physics(
        scene,
        environment_collider_ref=layer_ref,
        extra_provenance={
            "simulation_package": build_config["builder"],
            "collision_background_identity": background.identity,
        },
    )
    export_capability = assess_export_capabilities(
        enriched,
        runtime_qualified=runtime_qualified,
        runtime_version=runtime_version,
        resolve_artifact=registry.runtime_resolver.require,
    )
    if export_capability.status == ExportCapabilityStatus.BLOCKED:
        return SimulationPackage(
            job_id=job_id,
            source_scene_revision=scene.scene_revision,
            scene_revision=enriched.scene_revision,
            scene_ir_checksum=enriched.scene_ir_checksum,
            created_at=datetime.now(UTC),
            preflight=run_preflight(enriched),
            confirmed_objects=confirmed,
            environment_triangles=triangles,
            carved_triangles=carved,
            retained_shared_triangles=background.retained_shared_triangles,
            retained_shared_object_ids=list(background.retained_shared_object_ids),
            export_capability=export_capability,
        )

    report = run_preflight(enriched, artifact_store_root=root)
    if report.blocking_result != RuleResult.PASS:
        # Chưa đạt: không tạo revision; người dùng sửa theo báo cáo rồi tạo lại.
        return SimulationPackage(
            job_id=job_id,
            source_scene_revision=scene.scene_revision,
            scene_revision=enriched.scene_revision,
            scene_ir_checksum=enriched.scene_ir_checksum,
            created_at=datetime.now(UTC),
            preflight=report,
            confirmed_objects=confirmed,
            environment_triangles=triangles,
            carved_triangles=carved,
            retained_shared_triangles=background.retained_shared_triangles,
            retained_shared_object_ids=list(background.retained_shared_object_ids),
            export_capability=export_capability,
        )
    with tempfile.TemporaryDirectory(prefix="r2s_candidate_") as directory:
        output = Path(directory)
        try:
            hybrid = (
                _hybrid_layers(registry, enriched, output, background, hybrid_python, simulation_config=controls)
                if mode == EffectiveExportMode.HYBRID
                else None
            )
            if mode == EffectiveExportMode.HYBRID and hybrid is None:
                raise ValueError("hybrid USD capability đã chọn nhưng runner không tạo entrypoint")
            if mode == EffectiveExportMode.LEGACY_BOX:
                generate_scene_usda(enriched, ENVIRONMENT_LAYER, build_config=controls)
        except (ArtifactStoreError, OSError, ValueError):
            logger.exception("USD package build failed before SceneIR revision publication for job %s", job_id)
            failed_capability = export_capability.model_copy(
                update={
                    "status": ExportCapabilityStatus.BLOCKED,
                    "blockers": [
                        ExportCapabilityBlocker(
                            code="USD_EXPORT_FAILED",
                            message="The USD builder rejected the requested geometry or dependency closure; no scene revision or candidate was published.",
                            affected_object_ids=sorted(
                                item.id
                                for item in scene.objects
                                if item.active and item.state == SceneObjectState.CONFIRMED
                            ),
                        )
                    ],
                }
            )
            return SimulationPackage(
                job_id=job_id,
                source_scene_revision=scene.scene_revision,
                scene_revision=enriched.scene_revision,
                scene_ir_checksum=enriched.scene_ir_checksum,
                created_at=datetime.now(UTC),
                preflight=report,
                confirmed_objects=confirmed,
                environment_triangles=triangles,
                carved_triangles=carved,
                retained_shared_triangles=background.retained_shared_triangles,
                retained_shared_object_ids=list(background.retained_shared_object_ids),
                export_capability=failed_capability,
            )

        published = registry.scene.publish_next(job_id, scene.scene_revision, enriched, "physics_enrich").revision.scene
        report = run_preflight(
            published,
            artifact_store_root=root,
            artifact_resolver=registry.runtime_resolver.require,
        )
        if report.blocking_result != RuleResult.PASS:
            raise ValueError("preflight đổi kết quả sau khi publish revision; không đóng gói")
        if export_capability.scene_revision != published.scene_revision or (
            export_capability.scene_ir_checksum != published.scene_ir_checksum
        ):
            export_capability = assess_export_capabilities(
                published,
                runtime_qualified=runtime_qualified,
                runtime_version=runtime_version,
                resolve_artifact=registry.runtime_resolver.require,
            )
            if export_capability.status != ExportCapabilityStatus.SUPPORTED:
                raise ValueError("export capability đổi kết quả sau khi publish revision; không đóng gói")

        layers = {
            name: payload
            for name, payload in (hybrid or {}).items()
            if name not in {"scene.usda", "usd_export_summary.json"} and not name.startswith("assets/")
        }
        layer_refs = [
            _publish(
                registry,
                _reference(job_id, f"hybrid/{name}", "OpenUSDLayer", StageId.CANDIDATE_BUILD, payload),
                payload,
            )
            for name, payload in layers.items()
        ]
        config = build_config
        package = build_candidate_package(
            CandidateBuildRequest(
                scene=published,
                preflight_report=report,
                job_manifest_checksum=job.job_manifest_checksum,
                build_config=config,
                output_dir=output,
                job_id=job_id,
                environment_layer=ENVIRONMENT_LAYER,
                environment_layer_ref=layer_ref,
                entrypoint_bytes=hybrid["scene.usda"] if hybrid else None,
                extra_assets=layer_refs,
                export_mode=mode,
                export_capability=export_capability,
            )
        )
        entrypoint = (output / "scene.usda").read_bytes()
        _publish(registry, package.entrypoint_usd, entrypoint)
        archive = _zip_package(
            {
                "scene.usda": entrypoint,
                **layers,
                **{name: payload for name, payload in (hybrid or {}).items() if name.startswith("assets/")},
                ENVIRONMENT_LAYER: registry.runtime_resolver.require(layer_ref).read_bytes(),
                "candidate_manifest.json": (output / "candidate_manifest.json").read_bytes(),
                "candidate_package.json": package.model_dump_json(indent=2).encode(),
                "preflight_report.json": report.model_dump_json(indent=2).encode(),
                "export_capability.json": export_capability.model_dump_json(indent=2).encode(),
                **(
                    {"usd_export_summary.json": hybrid["usd_export_summary.json"]}
                    if hybrid is not None and "usd_export_summary.json" in hybrid
                    else {}
                ),
                "README.txt": _readme(
                    published,
                    package,
                    hybrid is not None,
                    build_config,
                    background.retained_shared_triangles,
                    background.retained_shared_object_ids,
                    sorted(item.id for item in published.objects if item.active and catalog_asset_provenance(item)),
                ).encode(),
            }
        )
    package_ref = _publish(
        registry,
        _reference(job_id, "simulation_package.zip", "SimulationPackageArchive", StageId.CANDIDATE_BUILD, archive),
        archive,
    )
    result = SimulationPackage(
        job_id=job_id,
        source_scene_revision=scene.scene_revision,
        scene_revision=published.scene_revision,
        scene_ir_checksum=published.scene_ir_checksum,
        created_at=datetime.now(UTC),
        preflight=report,
        confirmed_objects=confirmed,
        environment_triangles=triangles,
        carved_triangles=carved,
        retained_shared_triangles=background.retained_shared_triangles,
        retained_shared_object_ids=list(background.retained_shared_object_ids),
        export_capability=export_capability,
        candidate=package,
        package_ref=package_ref,
    )
    payload = result.model_dump_json(indent=2).encode()
    registry.scene.store.publish(
        ProductArtifactRef(
            artifact_type="SimulationPackageRecord",
            schema_version="1.0",
            artifact_uri=record_uri(job_id, published.scene_revision),
            artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.CANDIDATE_BUILD,
            job_id=job_id,
        ),
        payload,
    )
    return result


def _zip_package(files: dict[str, bytes]) -> bytes:
    """Zip tất định (mốc thời gian cố định) để cùng nội dung → cùng checksum."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _catalog_note(object_ids: Sequence[str]) -> list[str]:
    """README line for catalog objects exported as their box proxy (the asset bytes cannot be sealed)."""
    if not object_ids:
        return []
    return [
        f"Vật từ danh mục Isaac ({', '.join(object_ids)}) chỉ có collider hộp và vật lý đã khai báo; hình asset không "
        "nhúng vào gói. Nguồn asset nằm ở customData real2sim:catalog của từng vật."
    ]


def _retention_note(retained_triangles: int, object_ids: Sequence[str]) -> list[str]:
    """README line for background triangles kept because a carved and a kept source box share them."""
    if retained_triangles <= 0:
        return []
    return [
        f"Nền giữ lại {retained_triangles:,} tam giác nằm trong vùng chồng giữa vật bị khoét và ứng viên chưa xử lý "
        f"({', '.join(object_ids) or 'không rõ'}); xác nhận hoặc xoá các ứng viên đó rồi tạo lại gói để khoét hết."
    ]


def _readme(
    scene: SceneIR,
    package: CandidatePackage,
    hybrid: bool = False,
    build_config: dict[str, Any] | None = None,
    retained_shared_triangles: int = 0,
    retained_shared_object_ids: Sequence[str] = (),
    catalog_object_ids: Sequence[str] = (),
) -> str:
    config = build_config or (HYBRID_BUILD_CONFIG if hybrid else BUILD_CONFIG)
    retention = [
        *_retention_note(retained_shared_triangles, retained_shared_object_ids),
        *_catalog_note(catalog_object_ids),
    ]
    if hybrid:
        return "\n".join(
            [
                "Real2Sim Studio — gói mô phỏng USD lai (CandidatePackage, pipeline v2)",
                f"scene_id: {scene.scene_id}",
                f"scene_revision: {scene.scene_revision}",
                f"scene_ir_checksum: {scene.scene_ir_checksum}",
                f"candidate_checksum: {package.candidate_checksum}",
                "",
                "Mở scene.usda trong Isaac Sim ≥ 5.0 (metersPerUnit = 1, kilogramsPerUnit = 1, upAxis = Z).",
                "Không mở file .usdc làm stage gốc; scene.usda tham chiếu environment.usdc và objects/*.usdc.",
                "Hình ảnh: Gaussian (UsdVol ParticleField3DGaussianSplat) của nền đã vá và của từng vật đã xác nhận.",
                "Va chạm: environment.usdc/Collision là triangle mesh tĩnh theo source ownership; GroundPlane ở z = 0;",
                "mỗi vật dùng đúng AABB/OBB hoặc các mảnh convexHull đã khai báo; không tự đổi collider khi thiếu hình học.",
                "Local transform, khối lượng, RigidBody và vật liệu được ghi đúng theo ObjectPhysics; không tự đặt giá trị mặc định.",
                "nhãn lớp qua UsdSemantics LabelsAPI. Ứng viên chưa xác nhận nằm trong hình của nền, không có collider riêng.",
                "Vùng nền được vá là hình suy đoán (chưa từng được quay). Physics chưa được kiểm trong Isaac (SIM-06).",
                *retention,
                f"{ENVIRONMENT_LAYER}: bản collision-only của môi trường (tham khảo, scene.usda không dùng).",
                json.dumps(config, ensure_ascii=False),
                "",
            ]
        )
    return "\n".join(
        [
            "Real2Sim Studio — gói mô phỏng (CandidatePackage)",
            f"scene_id: {scene.scene_id}",
            f"scene_revision: {scene.scene_revision}",
            f"scene_ir_checksum: {scene.scene_ir_checksum}",
            f"candidate_checksum: {package.candidate_checksum}",
            "",
            "Mở scene.usda trong Isaac Sim (metersPerUnit = 1, upAxis = Z).",
            f"{ENVIRONMENT_LAYER}: collision mesh REC-05 đã bỏ source region của vật được xác nhận/đã xoá;",
            "sàn là GroundPlane ở z = 0; mỗi vật đã xác nhận có collider hộp riêng.",
            "USD có /World/PhysicsScene; Visual 3DGS không nằm trong gói; physics chưa được kiểm trong Isaac (SIM-06).",
            *retention,
            json.dumps(config, ensure_ascii=False),
            "",
        ]
    )
