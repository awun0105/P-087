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
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import trimesh
from pydantic import BaseModel, ConfigDict, Field

from src.config import get_settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.scene import (
    ColliderType,
    SceneIR,
    SceneObject,
    SceneObjectState,
)
from src.models.contracts.validation import CandidatePackage, PreflightReport, RuleResult
from src.services.orchestration.artifacts.errors import ArtifactStoreError
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.effective_collision import (
    _job_simulation_config,
    _recover_legacy_source_ownership,
)
from src.services.orchestration.scene.effective_collision import (
    effective_environment as _carved_environment,
)
from src.services.scene.effective_collision import CarvedBackground
from src.services.scene.representation_composition import VisualPolicy, scene_representations
from src.services.scene.representation_integrity import representation_issues
from src.services.simulation.colliders.carve import (
    COLLISION_CARVE_MARGIN_M,
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
    "capability_contract": "usd-export-capabilities-v3",
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
    "capability_contract": "usd-export-capabilities-v3",
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
    issues = representation_issues(scene, resolve)
    if issues:
        raise ValueError(f"visual representation incomplete: {issues}")
    dispositions = {item.object_id: item for item in scene_representations(scene)}
    objects, extra = [], []
    for item in scene.objects:
        disposition = dispositions[item.id]
        gaussians = item.visual_ref if item.visual_ref and item.visual_ref.artifact_type == "ObjectGaussians" else None
        if disposition.visual_policy == VisualPolicy.SOURCE:
            if disposition.source_visual_required and gaussians is not None:
                pose = disposition.source_transform
                if pose is None:
                    raise ValueError(f"source pose missing for {item.id}")
                extra.append({"ply": str(resolve(gaussians)), "translation": list(pose.translation_xyz)})
            continue
        if not disposition.export_as_object:
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
    if capability.builder_version != "usd-export-capabilities-v3" or capability.blockers:
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
