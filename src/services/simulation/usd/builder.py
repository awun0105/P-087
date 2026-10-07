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
from src.services.simulation.usd.capabilities import (
    EffectiveExportMode,
    ExportCapabilityReport,
    ExportCapabilityStatus,
    RuntimeQualificationStatus,
    export_requirements,
    validate_builder_mode,
)
from src.services.simulation.usd.usda import generate_scene_usda


class CandidateBuildRequest(BaseModel):
    """Yêu cầu đóng gói CandidatePackage."""

    scene: SceneIR
    preflight_report: PreflightReport
    job_manifest_checksum: Checksum
    build_config: dict[str, Any] = Field(default_factory=dict)
    output_dir: Path | None = None
    #: Job sở hữu artifact; None giữ quy ước cũ (dùng scene_id) cho fixture.
    job_id: str | None = None
    #: Layer collider môi trường (đường dẫn tương đối trong gói) và ref artifact của nó.
    environment_layer: str | None = None
    environment_layer_ref: ProductArtifactRef | None = None
    #: Pipeline v2 (ADR 0007): entrypoint USD lai dựng sẵn (thay bản collision-only sinh từ SceneIR) và
    #: các layer của nó; cả hai đi vào inventory nên `candidate_checksum` phủ toàn bộ gói.
    entrypoint_bytes: bytes | None = None
    extra_assets: list[ProductArtifactRef] = Field(default_factory=list)
    export_mode: EffectiveExportMode = EffectiveExportMode.LEGACY_BOX
    export_capability: ExportCapabilityReport | None = None


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


def _create_entrypoint_ref(owner: str, usda_bytes: bytes) -> ProductArtifactRef:
    """Tạo ProductArtifactRef cho file scene.usda entrypoint (đường dẫn theo nội dung)."""
    digest = hashlib.sha256(usda_bytes).hexdigest()
    return ProductArtifactRef(
        artifact_type="OpenUSDEntrypoint",
        schema_version="1.0",
        artifact_uri=f"artifact://jobs/{owner}/candidate/{digest}/scene.usda",
        artifact_checksum=f"sha256:{digest}",
        data_class="derived",
        producer_stage="ST-CANDIDATE-BUILD",
        job_id=owner,
    )


def _compute_config_checksum(config: dict[str, Any]) -> str:
    """Tính mã băm chuẩn hóa cho build_config."""
    canonical_bytes = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"


def build_candidate_package(req: CandidateBuildRequest) -> CandidatePackage:
    """Xây dựng và niêm phong CandidatePackage từ SceneIR đã qua Preflight PASS."""
    _validate_preflight_gate(req.scene, req.preflight_report)
    validate_builder_mode(req.scene, req.export_mode)
    if req.export_capability is not None:
        capability = req.export_capability
        if capability.status != ExportCapabilityStatus.SUPPORTED:
            raise ValueError("Không thể build CandidatePackage khi export capability bị chặn")
        if capability.blockers:
            raise ValueError("export capability báo SUPPORTED nhưng vẫn chứa blocker")
        if capability.builder_version != "usd-export-capabilities-v1":
            raise ValueError("export capability builder version không được hỗ trợ")
        if capability.scene_revision != req.scene.scene_revision:
            raise ValueError("export capability scene_revision không khớp với SceneIR")
        if capability.scene_ir_checksum != req.scene.scene_ir_checksum:
            raise ValueError("export capability scene_ir_checksum không khớp với SceneIR")
        if capability.effective_mode != req.export_mode:
            raise ValueError("export capability mode không khớp với CandidateBuildRequest")
        if (
            req.export_mode == EffectiveExportMode.HYBRID
            and capability.runtime_qualification != RuntimeQualificationStatus.QUALIFIED
        ):
            raise ValueError("hybrid CandidatePackage requires a qualified USD runtime")
        if req.export_mode == EffectiveExportMode.HYBRID and not capability.runtime_version:
            raise ValueError("hybrid CandidatePackage requires the qualified USD runtime version")
        if capability.requirements != export_requirements(req.scene):
            raise ValueError("export capability requirements không khớp với SceneIR")
    elif req.export_mode == EffectiveExportMode.HYBRID:
        raise ValueError("hybrid CandidatePackage requires a qualified export capability report")
    if req.export_mode == EffectiveExportMode.HYBRID and req.entrypoint_bytes is None:
        raise ValueError("hybrid CandidatePackage requires a generated USD entrypoint")
    if req.export_mode == EffectiveExportMode.LEGACY_BOX and req.entrypoint_bytes is not None:
        raise ValueError("legacy CandidatePackage cannot receive a hybrid USD entrypoint")

    usda_bytes = req.entrypoint_bytes or generate_scene_usda(req.scene, req.environment_layer).encode("utf-8")
    entrypoint_usd = _create_entrypoint_ref(req.job_id or req.scene.scene_id, usda_bytes)

    assets, geometry, colliders = _collect_scene_refs(req.scene)
    assets = [*assets, *req.extra_assets]
    if req.environment_layer_ref is not None:
        colliders.append(req.environment_layer_ref)
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
