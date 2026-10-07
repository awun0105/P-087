"""Tạo gói mô phỏng cho Isaac từ SceneIR hiện tại (nối EX-SIM SIM-02/03/04/05 vào luồng Studio).

1. Môi trường: collision mesh REC-05 của scene, bỏ source region theo ownership bất biến của
   object được xác nhận/đã xoá, ghi thành layer USD Mesh tĩnh; sàn là ground plane.
2. Vật: collider hộp từ kích thước primitive (SIM-02 qua `enrich_scene_physics`, SIM-03).
3. Preflight tĩnh (SIM-04) trên đúng revision sẽ đóng gói; FAIL thì trả báo cáo, không tạo
   revision mới.
4. PASS: publish revision SceneIR có physics, đóng gói CandidatePackage (SIM-05) và một file zip
   tải về. Bản ghi gói khoá theo revision: sửa scene sau đó thì gói cũ không còn là gói hiện tại.

Scene theo vật (pipeline v2, ADR 0007 — có `environment.visual_master_ref`): entrypoint là **USD lai**
do `usd/hybrid_runner.py` dựng trong runtime có usd-core: Gaussian (ParticleField) của nền + từng vật
đã xác nhận, collider phân rã lồi, RigidBody/khối lượng/vật liệu, nhãn. Ứng viên chưa xác nhận vẫn là
một phần hình của nền; vật đã loại/xoá/ẩn không xuất. Các layer nằm trong inventory của candidate.

Physics trong Isaac (SIM-06+) chạy ở máy RTX, ngoài phạm vi bước này.
"""

import hashlib
import io
import json
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict

from src.config import get_settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.scene import ColliderType, SceneIR, SceneObject, SceneObjectOrigin, SceneObjectState
from src.models.contracts.validation import CandidatePackage, PreflightReport, RuleResult
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.catalog import physics_for
from src.services.orchestration.scene.objects import object_volume_m3
from src.services.scene.collision_ownership import SourceCollisionOwnershipError, read_triangle_memberships
from src.services.simulation.colliders.carve import CarveBox, carve_triangle_mask, triangle_mask_in_box
from src.services.simulation.enrichment.service import enrich_scene_physics
from src.services.simulation.preflight.engine import run_preflight
from src.services.simulation.usd.builder import CandidateBuildRequest, build_candidate_package
from src.services.simulation.usd.usda import generate_mesh_layer_usda

ENVIRONMENT_LAYER = "environment_collision.usda"
BUILD_CONFIG = {
    "builder": "real2sim-studio-simulation-package-v2-source-owned",
    "environment": "rec05_collision_mesh_source_owned_triangle_mesh",
    "carve_margin_m": 0.05,
    "background_identity_algorithm": "source_geometry_checksum+removed_triangle_mask_v1",
    "ground_plane": True,
    "object_collider": "box_from_primitive_dimensions",
}
HYBRID_BUILD_CONFIG = {
    "builder": "real2sim-studio-simulation-package-v3-hybrid-source-owned",
    "environment": "inpainted_gaussians_particlefield+rec05_source_owned_collision_mesh",
    "carve_margin_m": 0.05,
    "background_identity_algorithm": "source_geometry_checksum+removed_triangle_mask_v1",
    "ground_plane": True,
    "object_visual": "per_object_gaussians_particlefield",
    "object_collider": "convex_decomposition_or_box",
    "object_physics": "rigid_body_mass_material_labels",
}
HYBRID_RUNNER = Path(__file__).resolve().parents[3] / "services/simulation/usd/hybrid_runner.py"


@dataclass(frozen=True)
class CarvedBackground:
    """Verified source collision mesh shared by all package builders."""

    vertices: np.ndarray
    faces: np.ndarray
    carved_triangles: int
    identity: str


class SimulationPackage(BaseModel):
    """Kết quả tạo gói cho một revision SceneIR; `package_ref` chỉ có khi preflight PASS."""

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


def current_package(registry: ProjectRegistry, job_id: str) -> SimulationPackage | None:
    """Gói của revision SceneIR hiện tại, nếu đã tạo."""
    revision = registry.scene.current(job_id).scene.scene_revision
    path = registry.runtime_resolver.locate(record_uri(job_id, revision))
    return SimulationPackage.model_validate_json(path.read_bytes()) if path is not None else None


def _source_region_removed(item: SceneObject) -> bool:
    """Whether this reconstructed object's immutable source region leaves the background."""
    if item.provenance.get("duplicated_from") is not None:
        return False
    review = item.provenance.get("review")
    return review == "DELETED" or (review != "IGNORED" and item.state == SceneObjectState.CONFIRMED)


def _carved_environment(registry: ProjectRegistry, scene: SceneIR) -> CarvedBackground:
    """Resolve the source-owned background; edited object transforms never define carve regions."""
    glb = registry.runtime_resolver.require(scene.environment.geometry_ref).read_bytes()
    source_checksum = f"sha256:{hashlib.sha256(glb).hexdigest()}"
    if source_checksum != scene.environment.geometry_ref.artifact_checksum:
        raise SourceCollisionOwnershipError("source collision bytes differ from SceneIR environment geometry checksum")

    mesh = trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh", process=False)
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces)
    if not len(faces):
        raise SourceCollisionOwnershipError("source collision mesh has no triangles")

    reconstructed = [item for item in scene.objects if item.origin == SceneObjectOrigin.RECONSTRUCTED]
    missing = [
        item.id
        for item in reconstructed
        if item.provenance.get("duplicated_from") is None
        and _source_region_removed(item)
        and item.source_collision is None
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
        if owner.object_id != item.id or owner.source_geometry_ref != scene.environment.geometry_ref:
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
    owner_indices = np.full(len(faces), -1, dtype=np.int32)
    remove_mask = np.zeros(len(faces), dtype=bool)
    for owner_index, (item, owner) in enumerate(zip(owned, owners, strict=True)):
        if owner.region_kind == "triangle_indices":
            indices = np.asarray(memberships[owner.object_id], dtype=np.intp)
        else:
            dimensions = owner.source_obb_dimensions_xyz_m
            if dimensions is None:
                raise SourceCollisionOwnershipError(f"{owner.object_id}: source OBB dimensions are missing")
            box = CarveBox.from_transform(owner.source_transform, dimensions)
            indices = np.flatnonzero(triangle_mask_in_box(centroids, box, BUILD_CONFIG["carve_margin_m"]))

        previous = owner_indices[indices]
        overlaps = np.flatnonzero(previous >= 0)
        if len(overlaps):
            triangle_index = int(indices[overlaps[0]])
            previous_owner = owned[int(previous[overlaps[0]])].id
            raise SourceCollisionOwnershipError(
                f"source triangle {triangle_index} is claimed by both {previous_owner} and {owner.object_id}"
            )
        owner_indices[indices] = owner_index
        if _source_region_removed(item):
            remove_mask[indices] = True

    background_hash = hashlib.sha256()
    identity_header = json.dumps(
        {
            "algorithm": "source_geometry_checksum+removed_triangle_mask_v1",
            "source_geometry_checksum": source_checksum,
            "source_triangle_count": len(faces),
            "carve_margin_m": BUILD_CONFIG["carve_margin_m"],
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
    )


def _prim_name(object_id: str) -> str:
    return "".join(char if char.isalnum() or char == "_" else "_" for char in object_id)


def _is_pending(item: SceneObject) -> bool:
    """Ứng viên chưa được xác nhận/loại/xoá: vẫn là một phần hình của nền khi xuất."""
    return item.state == SceneObjectState.CANDIDATE and item.provenance.get("review") not in {"IGNORED", "DELETED"}


def _hybrid_layers(
    registry: ProjectRegistry,
    scene: SceneIR,
    output: Path,
    background: CarvedBackground,
    python: Path | None,
) -> dict[str, bytes] | None:
    """Dựng USD lai cho scene theo vật; None nếu scene không phải v2 hoặc máy không có runtime usd-core.

    Trả `{đường dẫn tương đối trong gói: bytes}` gồm `scene.usda`, `environment.usdc`, `objects/*.usdc`.
    """
    if scene.environment.visual_master_ref is None or python is None:
        return None
    if not python.is_file():
        raise ValueError("USD runtime disappeared after hybrid package selection")
    resolve = registry.runtime_resolver.require
    collision = output / "environment_collision.ply"
    trimesh.Trimesh(background.vertices, background.faces, process=False).export(collision)
    objects, extra = [], []
    for item in scene.objects:
        gaussians = item.visual_ref if item.visual_ref and item.visual_ref.artifact_type == "ObjectGaussians" else None
        if _is_pending(item):
            if gaussians is not None:
                extra.append({"ply": str(resolve(gaussians)), "translation": list(item.transform.translation_xyz)})
            continue
        if not (item.active and item.state == SceneObjectState.CONFIRMED):
            continue
        convex = item.collider is not None and item.collider.collider_type == ColliderType.CONVEX_DECOMPOSITION
        physics = item.physics or physics_for(item.semantic_class, object_volume_m3(item))
        dimensions = item.primitive_dimensions_xyz_m
        asset_url = item.provenance.get("asset_url")
        objects.append(
            {
                "prim": _prim_name(item.id),
                "name": item.name,
                "translation": list(item.transform.translation_xyz),
                "rotation_xyzw": list(item.transform.rotation_quaternion_xyzw),
                "gaussians_ply": str(resolve(gaussians)) if gaussians is not None else None,
                "collision_glb": str(resolve(item.collider.geometry_ref))
                if convex and item.collider and item.collider.geometry_ref
                else None,
                "box_dims": list(dimensions) if dimensions else None,
                "semantic_class": item.semantic_class,
                "physics": physics.model_dump(mode="json"),
                "asset_usd": asset_url if isinstance(asset_url, str) else None,
                "asset_drop_m": dimensions[2] / 2 if dimensions else 0.0,
            }
        )
    request = {
        "output_dir": str(output / "hybrid"),
        "ground_plane": True,
        "collision_background_identity": background.identity,
        "environment": {
            "gaussians_ply": str(resolve(scene.environment.visual_master_ref)),
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
    root = output / "hybrid"
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _environment_layer(
    registry: ProjectRegistry, job_id: str, background: CarvedBackground
) -> tuple[ProductArtifactRef, int, int]:
    """Layer USD collider từ source-owned background; trả (ref, tam giác còn lại, tam giác bỏ)."""
    payload = generate_mesh_layer_usda(background.vertices, background.faces).encode("utf-8")
    reference = _reference(job_id, ENVIRONMENT_LAYER, "ColliderGeometry", StageId.COLLIDER, payload)
    return _publish(registry, reference, payload), int(len(background.faces)), background.carved_triangles


def _hybrid_runtime_python(scene: SceneIR) -> Path | None:
    """Return the pinned USD runtime only when this scene can use the hybrid builder."""
    python = get_settings().product_scene_runtime_python
    if scene.environment.visual_master_ref is None or python is None or not python.is_file():
        return None
    return python


def _package_build_config(hybrid: bool, background: CarvedBackground) -> dict[str, Any]:
    """Bind package identity to the exact source mesh and carved triangle mask."""
    base = HYBRID_BUILD_CONFIG if hybrid else BUILD_CONFIG
    return {**base, "collision_background_identity": background.identity}


def build_simulation_package(registry: ProjectRegistry, job_id: str) -> SimulationPackage:
    """Tạo (hoặc trả lại) gói mô phỏng của revision SceneIR hiện tại."""
    current = registry.scene.current(job_id)
    scene = current.scene
    existing = current_package(registry, job_id)
    if existing is not None:
        return existing
    job = registry.get_job(job_id)
    background = _carved_environment(registry, scene)
    layer_ref, triangles, carved = _environment_layer(registry, job_id, background)
    hybrid_python = _hybrid_runtime_python(scene)
    build_config = _package_build_config(hybrid_python is not None, background)
    enriched = enrich_scene_physics(
        scene,
        environment_collider_ref=layer_ref,
        extra_provenance={
            "simulation_package": build_config["builder"],
            "collision_background_identity": background.identity,
        },
    )
    root = registry.runtime_resolver.artifact_root
    confirmed = sum(1 for item in scene.objects if item.active and item.state == SceneObjectState.CONFIRMED)
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
        )
    published = registry.scene.publish_next(job_id, scene.scene_revision, enriched, "physics_enrich").revision.scene
    report = run_preflight(published, artifact_store_root=root)
    if report.blocking_result != RuleResult.PASS:
        raise ValueError("preflight đổi kết quả sau khi publish revision; không đóng gói")
    with tempfile.TemporaryDirectory(prefix="r2s_candidate_") as directory:
        output = Path(directory)
        hybrid = _hybrid_layers(registry, published, output, background, hybrid_python)
        layers = {name: payload for name, payload in (hybrid or {}).items() if name != "scene.usda"}
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
            )
        )
        entrypoint = (output / "scene.usda").read_bytes()
        _publish(registry, package.entrypoint_usd, entrypoint)
        archive = _zip_package(
            {
                "scene.usda": entrypoint,
                **layers,
                ENVIRONMENT_LAYER: registry.runtime_resolver.require(layer_ref).read_bytes(),
                "candidate_manifest.json": (output / "candidate_manifest.json").read_bytes(),
                "candidate_package.json": package.model_dump_json(indent=2).encode(),
                "preflight_report.json": report.model_dump_json(indent=2).encode(),
                "README.txt": _readme(published, package, hybrid is not None, build_config).encode(),
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


def _readme(
    scene: SceneIR,
    package: CandidatePackage,
    hybrid: bool = False,
    build_config: dict[str, Any] | None = None,
) -> str:
    config = build_config or (HYBRID_BUILD_CONFIG if hybrid else BUILD_CONFIG)
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
                "mỗi vật có các khối lồi (convexHull) hoặc hộp, RigidBody + khối lượng + vật liệu vật lý nếu là vật động,",
                "nhãn lớp qua UsdSemantics LabelsAPI. Ứng viên chưa xác nhận nằm trong hình của nền, không có collider riêng.",
                "Vùng nền được vá là hình suy đoán (chưa từng được quay). Physics chưa được kiểm trong Isaac (SIM-06).",
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
            "Visual 3DGS không nằm trong gói; physics chưa được kiểm trong Isaac (SIM-06).",
            json.dumps(config, ensure_ascii=False),
            "",
        ]
    )
