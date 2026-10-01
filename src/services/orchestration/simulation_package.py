"""Tạo gói mô phỏng cho Isaac từ SceneIR hiện tại (nối EX-SIM SIM-02/03/04/05 vào luồng Studio).

1. Môi trường: collision mesh REC-05 của scene, khoét chỗ các vật đã xác nhận (có collider hộp
   riêng), ghi thành layer USD Mesh tĩnh; sàn là ground plane (mesh REC-05 không chứa sàn).
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
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import trimesh
from pydantic import BaseModel, ConfigDict

from src.config import get_settings
from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.scene import ColliderType, SceneIR, SceneObject, SceneObjectState
from src.models.contracts.validation import CandidatePackage, PreflightReport, RuleResult
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.catalog import physics_for
from src.services.orchestration.scene.objects import object_volume_m3
from src.services.simulation.colliders.carve import CarveBox, carve_boxes
from src.services.simulation.enrichment.service import enrich_scene_physics
from src.services.simulation.preflight.engine import run_preflight
from src.services.simulation.usd.builder import CandidateBuildRequest, build_candidate_package
from src.services.simulation.usd.usda import generate_mesh_layer_usda

ENVIRONMENT_LAYER = "environment_collision.usda"
BUILD_CONFIG = {
    "builder": "real2sim-studio-simulation-package-v1",
    "environment": "rec05_collision_mesh_carved_triangle_mesh",
    "carve_margin_m": 0.05,
    "ground_plane": True,
    "object_collider": "box_from_primitive_dimensions",
}
HYBRID_BUILD_CONFIG = {
    "builder": "real2sim-studio-simulation-package-v2-hybrid",
    "environment": "inpainted_gaussians_particlefield+rec05_collision_mesh_carved",
    "carve_margin_m": 0.05,
    "ground_plane": True,
    "object_visual": "per_object_gaussians_particlefield",
    "object_collider": "convex_decomposition_or_box",
    "object_physics": "rigid_body_mass_material_labels",
}
HYBRID_RUNNER = Path(__file__).resolve().parents[2] / "services/simulation/usd/hybrid_runner.py"


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
    if registry.runtime_resolver.resolve(reference.artifact_uri).is_file():
        return reference
    return registry.scene.store.publish(reference, payload)


def current_package(registry: ProjectRegistry, job_id: str) -> SimulationPackage | None:
    """Gói của revision SceneIR hiện tại, nếu đã tạo."""
    revision = registry.scene.current(job_id).scene.scene_revision
    path = registry.runtime_resolver.resolve(record_uri(job_id, revision))
    return SimulationPackage.model_validate_json(path.read_bytes()) if path.is_file() else None


def _carved_environment(registry: ProjectRegistry, scene: SceneIR) -> tuple[np.ndarray, np.ndarray, int]:
    """Collision mesh môi trường đã khoét chỗ vật đã xác nhận: (đỉnh, mặt, số tam giác bỏ)."""
    glb = registry.runtime_resolver.require(scene.environment.geometry_ref).read_bytes()
    mesh = trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh")
    boxes = [
        CarveBox.from_transform(item.transform, item.primitive_dimensions_xyz_m)
        for item in scene.objects
        if item.active and item.state == SceneObjectState.CONFIRMED and item.primitive_dimensions_xyz_m
    ]
    return carve_boxes(
        np.asarray(mesh.vertices, dtype=float), np.asarray(mesh.faces), boxes, BUILD_CONFIG["carve_margin_m"]
    )


def _prim_name(object_id: str) -> str:
    return "".join(char if char.isalnum() or char == "_" else "_" for char in object_id)


def _is_pending(item: SceneObject) -> bool:
    """Ứng viên chưa được xác nhận/loại/xoá: vẫn là một phần hình của nền khi xuất."""
    return item.state == SceneObjectState.CANDIDATE and item.provenance.get("review") not in {"IGNORED", "DELETED"}


def _hybrid_layers(registry: ProjectRegistry, scene: SceneIR, output: Path) -> dict[str, bytes] | None:
    """Dựng USD lai cho scene theo vật; None nếu scene không phải v2 hoặc máy không có runtime usd-core.

    Trả `{đường dẫn tương đối trong gói: bytes}` gồm `scene.usda`, `environment.usdc`, `objects/*.usdc`.
    """
    python = get_settings().product_scene_runtime_python
    if scene.environment.visual_master_ref is None or python is None or not python.is_file():
        return None
    resolve = registry.runtime_resolver.require
    vertices, faces, _ = _carved_environment(registry, scene)
    collision = output / "environment_collision.ply"
    trimesh.Trimesh(vertices, faces, process=False).export(collision)
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


def _environment_layer(registry: ProjectRegistry, job_id: str, scene: SceneIR) -> tuple[ProductArtifactRef, int, int]:
    """Layer USD collider môi trường đã khoét vật; trả (ref, số tam giác còn lại, số tam giác bỏ)."""
    vertices, faces, carved = _carved_environment(registry, scene)
    payload = generate_mesh_layer_usda(vertices, faces).encode("utf-8")
    reference = _reference(job_id, ENVIRONMENT_LAYER, "ColliderGeometry", StageId.COLLIDER, payload)
    return _publish(registry, reference, payload), int(len(faces)), carved


def build_simulation_package(registry: ProjectRegistry, job_id: str) -> SimulationPackage:
    """Tạo (hoặc trả lại) gói mô phỏng của revision SceneIR hiện tại."""
    existing = current_package(registry, job_id)
    if existing is not None:
        return existing
    current = registry.scene.current(job_id)
    scene = current.scene
    job = registry.get_job(job_id)
    layer_ref, triangles, carved = _environment_layer(registry, job_id, scene)
    enriched = enrich_scene_physics(
        scene,
        environment_collider_ref=layer_ref,
        extra_provenance={"simulation_package": BUILD_CONFIG["builder"]},
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
        hybrid = _hybrid_layers(registry, published, output)
        layers = {name: payload for name, payload in (hybrid or {}).items() if name != "scene.usda"}
        layer_refs = [
            _publish(
                registry,
                _reference(job_id, f"hybrid/{name}", "OpenUSDLayer", StageId.CANDIDATE_BUILD, payload),
                payload,
            )
            for name, payload in layers.items()
        ]
        config = HYBRID_BUILD_CONFIG if hybrid else BUILD_CONFIG
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
                "README.txt": _readme(published, package, hybrid is not None).encode(),
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


def _readme(scene: SceneIR, package: CandidatePackage, hybrid: bool = False) -> str:
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
                "Va chạm: environment.usdc/Collision là triangle mesh tĩnh (đã khoét chỗ vật); GroundPlane ở z = 0;",
                "mỗi vật có các khối lồi (convexHull) hoặc hộp, RigidBody + khối lượng + vật liệu vật lý nếu là vật động,",
                "nhãn lớp qua UsdSemantics LabelsAPI. Ứng viên chưa xác nhận nằm trong hình của nền, không có collider riêng.",
                "Vùng nền được vá là hình suy đoán (chưa từng được quay). Physics chưa được kiểm trong Isaac (SIM-06).",
                f"{ENVIRONMENT_LAYER}: bản collision-only của môi trường (tham khảo, scene.usda không dùng).",
                json.dumps(HYBRID_BUILD_CONFIG, ensure_ascii=False),
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
            f"{ENVIRONMENT_LAYER}: collision mesh môi trường (REC-05) đã khoét chỗ vật đã xác nhận;",
            "sàn là GroundPlane ở z = 0; mỗi vật đã xác nhận có collider hộp riêng.",
            "Visual 3DGS không nằm trong gói; physics chưa được kiểm trong Isaac (SIM-06).",
            json.dumps(BUILD_CONFIG, ensure_ascii=False),
            "",
        ]
    )
