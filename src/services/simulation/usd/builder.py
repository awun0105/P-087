"""Dịch vụ đóng gói CandidatePackage cho Isaac Sim validation (SIM-05).

Xây dựng gói bất biến CandidatePackage chứa entrypoint OpenUSD, danh mục kiểm kê
CandidateManifest, và mã băm niêm phong candidate_checksum.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.models.contracts.artifacts import Checksum, ProductArtifactRef
from src.models.contracts.identity import (
    canonical_content_checksum,
    verify_candidate_inventory,
    verify_content_checksum,
)
from src.models.contracts.scene import SceneIR
from src.models.contracts.validation import (
    CandidateManifest,
    CandidatePackage,
    ObjectTransform,
    PreflightReport,
    RuleResult,
)
from src.services.simulation.usd.usda import generate_scene_usda


class CandidateBuildRequest(BaseModel):
    """Yêu cầu đóng gói CandidatePackage."""

    scene: SceneIR
    preflight_report: PreflightReport
    job_manifest_checksum: Checksum
    build_config: dict[str, Any] = Field(default_factory=dict)
    output_dir: Path | None = None


def _validate_preflight_gate(scene: SceneIR, report: PreflightReport) -> None:
    """Kiểm tra Preflight report phải PASS và khớp chính xác bản sửa đổi SceneIR."""
    if report.blocking_result != RuleResult.PASS:
        raise ValueError(
            f"Không thể build CandidatePackage khi Preflight chưa PASS (hiện tại: {report.blocking_result})"
        )
    if report.scene_revision != scene.scene_revision:
        raise ValueError(
            f"Preflight report scene_revision '{report.scene_revision}' không khớp với "
            f"scene.scene_revision '{scene.scene_revision}'"
        )
    if report.scene_ir_checksum != scene.scene_ir_checksum:
        raise ValueError("Preflight report scene_ir_checksum không khớp với scene.scene_ir_checksum")


def _collect_scene_refs(
    scene: SceneIR,
) -> tuple[list[ProductArtifactRef], list[ProductArtifactRef], list[ProductArtifactRef]]:
    """Thu thập danh mục tài nguyên assets, geometry và colliders từ SceneIR."""
    assets: list[ProductArtifactRef] = []
    geometry: list[ProductArtifactRef] = [scene.environment.geometry_ref]
    colliders: list[ProductArtifactRef] = []

    if scene.environment.collider_ref is not None:
        colliders.append(scene.environment.collider_ref)

    for obj in scene.objects:
        if not obj.active:
            continue
        geometry.append(obj.geometry_ref)
        if obj.asset_ref is not None:
            assets.append(obj.asset_ref)
        if obj.collider is not None and obj.collider.geometry_ref is not None:
            colliders.append(obj.collider.geometry_ref)

    return assets, geometry, colliders


def _create_entrypoint_ref(scene_id: str, usda_bytes: bytes) -> ProductArtifactRef:
    """Tạo ProductArtifactRef cho file scene.usda entrypoint."""
    digest = hashlib.sha256(usda_bytes).hexdigest()
    return ProductArtifactRef(
        artifact_type="OpenUSDEntrypoint",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{scene_id}/candidate/scene.usda",
        artifact_checksum=f"sha256:{digest}",
        data_class="derived",
        producer_stage="ST-CANDIDATE-BUILD",
        job_id=scene_id,
    )


def _compute_config_checksum(config: dict[str, Any]) -> str:
    """Tính mã băm chuẩn hóa cho build_config."""
    canonical_bytes = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"


def build_candidate_package(req: CandidateBuildRequest) -> CandidatePackage:
    """Xây dựng và niêm phong CandidatePackage từ SceneIR đã qua Preflight PASS."""
    _validate_preflight_gate(req.scene, req.preflight_report)

    usda_text = generate_scene_usda(req.scene)
    usda_bytes = usda_text.encode("utf-8")
    entrypoint_usd = _create_entrypoint_ref(req.scene.scene_id, usda_bytes)

    assets, geometry, colliders = _collect_scene_refs(req.scene)
    ordered_refs = [entrypoint_usd, *assets, *geometry, *colliders]
    artifact_checksums = [ref.artifact_checksum for ref in ordered_refs]

    obj_transforms = [
        ObjectTransform(object_id=obj.id, transform=obj.transform) for obj in req.scene.objects if obj.active
    ]

    manifest = CandidateManifest(
        schema_version="1.0",
        candidate_id=f"candidate-{req.scene.scene_id}-{req.scene.scene_revision}",
        scene_revision=req.scene.scene_revision,
        scene_ir_checksum=req.scene.scene_ir_checksum,
        job_manifest_checksum=req.job_manifest_checksum,
        coordinate_system=req.scene.coordinate_system,
        object_transforms=obj_transforms,
        asset_refs=assets,
        collider_refs=colliders,
        artifact_checksums=artifact_checksums,
        build_config_checksum=_compute_config_checksum(req.build_config),
    )

    temp_pkg = CandidatePackage(
        candidate_manifest=manifest,
        entrypoint_usd=entrypoint_usd,
        assets=assets,
        geometry=geometry,
        colliders=colliders,
        candidate_checksum="sha256:" + "0" * 64,
    )

    candidate_checksum = canonical_content_checksum(temp_pkg, "candidate_checksum")
    sealed_pkg = temp_pkg.model_copy(update={"candidate_checksum": candidate_checksum})

    # Xác thực bất biến theo các hợp đồng bắt buộc
    verify_candidate_inventory(sealed_pkg)
    verify_content_checksum(sealed_pkg, "candidate_checksum")

    if req.output_dir is not None:
        req.output_dir.mkdir(parents=True, exist_ok=True)
        (req.output_dir / "scene.usda").write_bytes(usda_bytes)
        (req.output_dir / "candidate_manifest.json").write_text(
            manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )

    return sealed_pkg
