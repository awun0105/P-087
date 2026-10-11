"""Xuất bản và quản lý RGB Geometry artifact (collision.glb) cho REC-05."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from src.models.contracts.artifacts import ArtifactDataClass, Checksum, ContractModel, ProductArtifactRef
from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.identity import canonical_json_bytes
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import GeometryArtifact, PreprocessingProvenance
from src.services.reconstruction.adapters.voxel import ProductVoxelRequest, SplatTransformVoxelAdapter
from src.services.reconstruction.adapters.voxel_clearance import clearance_from_bytes
from src.services.reconstruction.adapters.voxel_octree import VoxelOctree
from src.services.reconstruction.adapters.voxel_output import VoxelMetadata
from src.services.reconstruction.attempt import PathSegment
from src.services.reconstruction.rgb.canonical.metric import MetricCanonicalizer
from src.services.reconstruction.rgb.canonical.metric_models import MetricConfirmation
from src.services.reconstruction.rgb.canonical.metric_seed import CameraSeedProposal
from src.services.reconstruction.rgb.frames.frame_set import _sha256
from src.services.reconstruction.rgb.geometry.geometry_artifact import (
    GeometryArtifactInput,
    _voxel_summary,
    build_geometry_artifact,
)
from src.services.reconstruction.rgb.geometry.voxel import VoxelConfig
from src.services.reconstruction.rgb.preflight.publication import ArtifactWriter
from src.services.reconstruction.rgb.splat.visual_publication import VisualResolver


class GeometryExecutionRequest(ContractModel):
    """Yêu cầu tạo coarse voxel collision mesh từ visual artifact và metric confirmation."""

    execution_scope: Literal["product", "synthetic_fixture"] = "product"
    attempt_id: PathSegment | None = None
    confirmation_ref: ProductArtifactRef
    source_visual: ProductArtifactRef
    config: VoxelConfig
    job_id: str
    applied_record_checksum: Checksum | None = None
    seed_proposal: CameraSeedProposal | None = None


class SeedClearanceArtifacts(ContractModel):
    """Bằng chứng re-verify clearance; consumer không đọc lại workspace của attempt.

    Occupancy/binary là input đã dùng để quyết định seed, clearance là quyết định.
    Thiếu ba ref này thì consumer chỉ còn cách tin report của producer.
    """

    occupancy_metadata: ProductArtifactRef
    occupancy_binary: ProductArtifactRef
    seed_clearance: ProductArtifactRef


class GeometryExecutionResult(ContractModel):
    """Kết quả hoàn chỉnh của stage RGB Geometry."""

    geometry_ref: ProductArtifactRef
    metadata_ref: ProductArtifactRef
    voxel_binary_ref: ProductArtifactRef
    manifest_ref: ProductArtifactRef
    clearance: SeedClearanceArtifacts
    geometry: GeometryArtifact
    report: dict


class GeometryArtifactManifest(ContractModel):
    """Inventory portable; manifest chỉ publish sau khi mọi member đã tồn tại."""

    schema_version: Literal["1.1"] = "1.1"
    geometry: GeometryArtifact
    metadata_ref: ProductArtifactRef
    voxel_binary_ref: ProductArtifactRef
    clearance: SeedClearanceArtifacts


class GeometryPublisher:
    """Quản lý xuất bản bất biến cho collision mesh và voxel metadata."""

    def __init__(self, writer: ArtifactWriter, job_id: str) -> None:
        self.writer = writer
        self.job_id = job_id

    def for_job(self, job_id: str) -> "GeometryPublisher":
        """Tạo instance publisher trỏ tới job_id mục tiêu."""
        return GeometryPublisher(self.writer, job_id)

    def _publish(self, artifact_type: str, name: str, payload: bytes, provenance: dict) -> ProductArtifactRef:
        """Mọi artifact REC-05 dùng chung identity shape; chỉ khác artifact_type."""
        identity = provenance.get("publication_id") or hashlib.sha256(payload).hexdigest()
        ref = ProductArtifactRef(
            artifact_type=artifact_type,
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{self.job_id}/rec05/{identity}/{name}",
            artifact_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.RGB_GEOMETRY,
            job_id=self.job_id,
            source_provenance=provenance,
        )
        if self.writer.publish(ref, payload) != ref:
            raise ValueError(f"artifact writer changed {artifact_type} identity")
        return ref

    def publish_mesh(self, name: str, payload: bytes, provenance: dict) -> ProductArtifactRef:
        """Xuất bản collision mesh glb với provenance đầy đủ."""
        return self._publish("RgbGeometry", name, payload, provenance)

    def publish_metadata(self, name: str, payload: bytes, provenance: dict) -> ProductArtifactRef:
        """Xuất bản metadata voxel đi kèm."""
        return self._publish("VoxelMetadata", name, payload, provenance)

    def publish_occupancy(self, name: str, payload: bytes, provenance: dict) -> ProductArtifactRef:
        """Xuất bản occupancy json/bin mà clearance đã dùng làm căn cứ."""
        return self._publish("VoxelOccupancy", name, payload, provenance)

    def publish_clearance(self, name: str, payload: bytes, provenance: dict) -> ProductArtifactRef:
        """Xuất bản quyết định seed, gồm cả relocation nếu có."""
        return self._publish("SeedClearance", name, payload, provenance)


class GeometryResolver:
    """Đọc và thẩm định RGB geometry artifacts từ artifact store."""

    def __init__(self, resolve: Callable[[ProductArtifactRef], Path]) -> None:
        self.resolve = resolve

    def require(self, reference: ProductArtifactRef) -> Path:
        """Kiểm tra sự tồn tại và tính toàn vẹn sha256 của file."""
        path = self.resolve(reference)
        if not path.is_file() or _sha256(path) != reference.artifact_checksum:
            raise ValueError("geometry artifact missing or checksum mismatch")
        return path

    def load_metadata(self, reference: ProductArtifactRef) -> dict:
        """Đọc nội dung JSON của voxel metadata."""
        if reference.artifact_type != "VoxelMetadata":
            raise ValueError("reference is not a VoxelMetadata artifact")
        return json.loads(self.require(reference).read_text())

    def load(self, reference: ProductArtifactRef) -> GeometryArtifactManifest:
        """Consumer không cần attempt workspace; bind kernel/config với geometry đã ký hash."""
        manifest = GeometryArtifactManifest.model_validate_json(
            self._require_type(reference, "GeometryArtifactManifest").read_bytes()
        )
        geometry = manifest.geometry
        metadata = VoxelMetadata.model_validate_json(
            self._require_type(manifest.metadata_ref, "VoxelMetadata").read_bytes()
        )
        VoxelOctree(metadata, self._require_type(manifest.voxel_binary_ref, "VoxelBinary").read_bytes())
        if geometry.voxel != _voxel_summary(metadata.model_dump(mode="json", by_alias=True)):
            raise ValueError("geometry voxel bounds differ from published metadata")
        refs = (
            manifest.metadata_ref,
            manifest.voxel_binary_ref,
            manifest.clearance.occupancy_metadata,
            manifest.clearance.occupancy_binary,
            manifest.clearance.seed_clearance,
        )
        prefix = reference.artifact_uri.rsplit("/", 1)[0] + "/"
        for ref in refs:
            if ref.job_id != reference.job_id or not ref.artifact_uri.startswith(prefix):
                raise ValueError("geometry inventory differs from publication job/namespace")
            self.require(ref)
        if geometry.job_id != reference.job_id or not geometry.artifact_uri.startswith(prefix):
            raise ValueError("geometry belongs to another publication")
        self.require(
            ProductArtifactRef(
                artifact_type="RgbGeometry",
                schema_version="1.0",
                artifact_uri=geometry.artifact_uri,
                artifact_checksum=geometry.artifact_checksum,
                job_id=geometry.job_id,
                data_class="derived",
                producer_stage=StageId.RGB_GEOMETRY,
            )
        )
        decision = self.load_seed_clearance(manifest.clearance)
        config = VoxelConfig.model_validate(decision["config"])
        if (
            geometry.seed.requested_world_m != tuple(decision["requested_seed_world"])
            or geometry.seed.accepted_world_m != tuple(decision["accepted_seed_world"])
            or geometry.seed.clearance_evidence_checksum != manifest.clearance.seed_clearance.artifact_checksum
            or geometry.seed.occupancy_checksum != manifest.clearance.occupancy_binary.artifact_checksum
            or geometry.capsule.shape != "clearance_cylinder"
            or geometry.capsule.height_m != config.capsule_height_m
            or geometry.capsule.radius_m != config.capsule_radius_m
            or geometry.voxel.resolution_m != config.resolution_m
        ):
            raise ValueError("geometry seed/footprint differs from verified clearance config")
        return manifest

    def load_seed_clearance(self, clearance: SeedClearanceArtifacts) -> dict:
        """Re-verify clearance end-to-end từ bytes đã publish, không tin giá trị `status`.

        Đây là phía consumer của invariant: kernel ghi trong quyết định phải thật sự
        không chạm occupancy, và occupancy phải là đúng bytes mà quyết định dùng.
        """
        decision = json.loads(self._require_type(clearance.seed_clearance, "SeedClearance").read_text())
        meta_bytes = self._require_type(clearance.occupancy_metadata, "VoxelOccupancy").read_bytes()
        payload = self._require_type(clearance.occupancy_binary, "VoxelOccupancy").read_bytes()
        if "sha256:" + hashlib.sha256(meta_bytes).hexdigest() != decision["occupancy_metadata_checksum"]:
            raise ValueError("published occupancy metadata differs from the seed clearance decision")
        if "sha256:" + hashlib.sha256(payload).hexdigest() != decision["occupancy_binary_checksum"]:
            raise ValueError("published occupancy binary differs from the seed clearance decision")
        refs = (clearance.seed_clearance, clearance.occupancy_metadata, clearance.occupancy_binary)
        if len({ref.job_id for ref in refs}) != 1:
            raise ValueError("clearance artifacts belong to different jobs")
        config = VoxelConfig.model_validate(decision.get("config", {}))
        if decision != clearance_from_bytes(config, meta_bytes, payload):
            raise ValueError("published seed clearance decision differs from occupancy/config replay")
        return decision

    def _require_type(self, reference: ProductArtifactRef, artifact_type: str) -> Path:
        if reference.artifact_type != artifact_type:
            raise ValueError(f"reference is not a {artifact_type} artifact")
        return self.require(reference)


@dataclass(frozen=True)
class GeometryDependencies:
    """Dependencies được inject cho RgbGeometryService."""

    canonicalizer: MetricCanonicalizer
    visuals: VisualResolver
    adapter: SplatTransformVoxelAdapter
    publisher: GeometryPublisher
    verify_seed: Callable[[GeometryExecutionRequest], bool] | None = None


class RgbGeometryService:
    """Service điều phối toàn bộ pipeline tạo RGB Geometry (REC-05)."""

    def __init__(self, deps: GeometryDependencies) -> None:
        self.deps = deps

    def execute(self, request: GeometryExecutionRequest, workspace: Path) -> GeometryExecutionResult:
        """Thực thi pipeline voxelization, carve và xuất bản collision mesh."""
        request = GeometryExecutionRequest.model_validate(request.model_dump())
        confirmation, master_path = self._validate_preconditions(request)
        voxel_req = ProductVoxelRequest(
            confirmation=confirmation,
            source=master_path,
            source_checksum=confirmation.preview.request.anchor.source_master.artifact_checksum,
            config=request.config,
            applied_record_checksum=request.applied_record_checksum,
        )
        report = self.deps.adapter.run_product(voxel_req, workspace)
        report["preprocessing_provenance"] = _source_lineage(request, confirmation).model_dump(mode="json")
        return self._publish_artifacts(request, workspace, report)

    def _validate_preconditions(self, request: GeometryExecutionRequest) -> tuple:
        if request.applied_record_checksum is not None:
            raise ValueError("metric transform already applied; refusing double scaling")
        confirmation = (
            self.deps.canonicalizer.require_real(request.confirmation_ref)
            if request.execution_scope == "product"
            else self.deps.canonicalizer.load(request.confirmation_ref)
        )
        if (
            request.execution_scope == "synthetic_fixture"
            and confirmation.preview.request.evidence_kind != "synthetic_fixture"
        ):
            raise ValueError("fixture execution cannot bypass real scene seed validation")
        # Adapter luôn tự kiểm occupancy thật; callback là policy gate của caller, không
        # thay thế được nên product vẫn phải configure, để thiếu config không im lặng lọt.
        if request.execution_scope == "product" and (
            self.deps.verify_seed is None or self.deps.verify_seed(request) is not True
        ):
            raise ValueError("product capsule/seed clearance policy is not configured or rejected input")
        if confirmation.status != "CONFIRMED":
            raise ValueError("metric confirmation must be CONFIRMED")
        visual = self.deps.visuals.load(request.source_visual)
        if visual.master != confirmation.preview.request.anchor.source_master:
            raise ValueError("visual master does not match anchor source master")
        if request.seed_proposal is not None:
            if request.seed_proposal.confirmation_checksum != confirmation.record_checksum:
                raise ValueError("seed proposal does not match confirmation record")
        master_path = self.deps.visuals.require(visual.master)
        return confirmation, master_path

    def _publish_artifacts(
        self, request: GeometryExecutionRequest, workspace: Path, report: dict
    ) -> GeometryExecutionResult:

        # Validate toàn bộ graph trước lần ghi đầu; manifest là commit marker cuối.
        if request.config.external_fill_size_m is not None:
            expected_fill = {
                "status": "applied",
                "size_m": request.config.external_fill_size_m,
                "occupancy_log_checksum": _sha256(workspace / "occupancy.log"),
                "collision_log_checksum": _sha256(workspace / "collision.log"),
            }
            if report.get("external_fill") != expected_fill:
                raise ValueError("external fill report differs from the requested configuration or process logs")
        batch = _PublicationBatch()
        pub = GeometryPublisher(batch, request.job_id)
        provenance = _provenance(request, report)
        geometry_ref = pub.publish_mesh("collision.glb", (workspace / "collision.glb").read_bytes(), provenance)
        metadata_ref = pub.publish_metadata(
            "geometry.voxel.json", (workspace / "geometry.voxel.json").read_bytes(), provenance
        )
        binary_ref = pub._publish(
            "VoxelBinary", "geometry.voxel.bin", (workspace / "geometry.voxel.bin").read_bytes(), provenance
        )
        clearance = _publish_clearance(pub, workspace, provenance)
        geometry = _build_geometry_artifact(request, report, geometry_ref, clearance, workspace)
        inventory = GeometryArtifactManifest(
            geometry=geometry, metadata_ref=metadata_ref, voxel_binary_ref=binary_ref, clearance=clearance
        )
        manifest_ref = pub._publish(
            "GeometryArtifactManifest", "geometry.json", canonical_json_bytes(inventory), provenance
        )
        result = GeometryExecutionResult(
            geometry_ref=geometry_ref,
            metadata_ref=metadata_ref,
            voxel_binary_ref=binary_ref,
            manifest_ref=manifest_ref,
            clearance=clearance,
            geometry=geometry,
            report=report,
        )
        for reference, payload in batch.items:
            if self.deps.publisher.writer.publish(reference, payload) != reference:
                raise ValueError("artifact writer changed geometry publication identity")
        return result


def _build_geometry_artifact(
    request: GeometryExecutionRequest,
    report: dict,
    geometry_ref: ProductArtifactRef,
    clearance: SeedClearanceArtifacts,
    workspace: Path,
) -> GeometryArtifact:
    """Shared contract cho EX-SIM; validator chặn metric chưa CONFIRMED và seed không khớp relocation."""
    return build_geometry_artifact(
        GeometryArtifactInput(
            job_id=request.job_id,
            artifact_uri=geometry_ref.artifact_uri,
            artifact_checksum=geometry_ref.artifact_checksum,
            clearance_checksum=clearance.seed_clearance.artifact_checksum,
            source_master_checksum=report["source_checksum"],
            report=report,
            clearance_receipt=json.loads((workspace / "seed-clearance.json").read_text()),
        )
    )


def _provenance(request: GeometryExecutionRequest, report: dict) -> dict:
    """Provenance chung cho mọi artifact REC-05; không ghi path hay secret."""
    # Caller worker khóa attempt_id; caller legacy cũng không đè artifact của lần chạy trước.
    attempt_id = request.attempt_id or uuid4().hex
    return dict(
        attempt_id=attempt_id,
        publication_id=hashlib.sha256(
            canonical_json_bytes(
                {"request": request.model_dump(mode="json"), "files": report["files"], "attempt_id": attempt_id}
            )
        ).hexdigest(),
        producer_version="rec05-v2" if request.config.schema_version == "1.2" else "rec05-v1",
        applied_confirmation_checksum=report["applied_confirmation_checksum"],
        scale_applied=report["scale_applied"],
        applied_transform=report["applied_transform"],
        evidence_kind=report["evidence_kind"],
        source_checksum=report["source_checksum"],
        metric_derivative_checksum=report["files"]["input.ply"],
        metric_confirmation_ref=request.confirmation_ref.model_dump(mode="json"),
        voxel_resolution_m=request.config.resolution_m,
        voxel_config_checksum=request.config.checksum(),
        coordinate_system=CoordinateSystem().model_dump(mode="json"),
        preprocessing_provenance=report["preprocessing_provenance"],
        **({"external_fill": report["external_fill"]} if request.config.schema_version == "1.2" else {}),
    )


class _PublicationBatch:
    """Stage payloads trong RAM; invalid contract không tạo artifact dở dang."""

    def __init__(self) -> None:
        self.items: list[tuple[ProductArtifactRef, bytes]] = []

    def publish(self, reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        self.items.append((reference, payload))
        return reference


def _source_lineage(request: GeometryExecutionRequest, confirmation: MetricConfirmation) -> PreprocessingProvenance:
    """Giữ measurement/frame/decision provenance; không tự tẩy GT-assistance."""
    metric = confirmation.preview.request
    refs = {
        "visual": request.source_visual,
        "master": metric.anchor.source_master,
        "measurement": metric.anchor.measurement_ref,
        "frame": metric.frame.evidence_ref,
        "decision": confirmation.acceptance.decision_ref,
        "confirmation": request.confirmation_ref,
    }
    dependencies = []
    for role, ref in refs.items():
        provenance = ref.source_provenance or {}
        inherited = provenance.get("preprocessing_provenance", provenance)
        if "dependencies" in inherited:
            dependencies.extend(PreprocessingProvenance.model_validate(inherited).dependencies)
        dependencies.append(
            dict(
                role=role,
                origin="ground_truth"
                if inherited.get("ground_truth_assisted")
                else ("estimated" if role in {"visual", "master"} else "external"),
                source_checksum=ref.artifact_checksum,
            )
        )
    raw = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in dependencies]
    return PreprocessingProvenance(
        dependencies=raw,
        ground_truth_assisted=any(item["origin"] == "ground_truth" for item in raw),
        details={role: ref.model_dump(mode="json") for role, ref in refs.items()},
    )


def _publish_clearance(pub: GeometryPublisher, workspace: Path, provenance: dict) -> SeedClearanceArtifacts:
    """Publish cả ba bằng chứng; thiếu file là lỗi pipeline chứ không phải lỗi publish."""

    def read(name: str) -> bytes:
        path = workspace / name
        if not path.is_file():
            raise ValueError(f"attempt workspace is missing required clearance evidence {name}")
        return path.read_bytes()

    return SeedClearanceArtifacts(
        occupancy_metadata=pub.publish_occupancy("occupancy.voxel.json", read("occupancy.voxel.json"), provenance),
        occupancy_binary=pub.publish_occupancy("occupancy.voxel.bin", read("occupancy.voxel.bin"), provenance),
        seed_clearance=pub.publish_clearance("seed-clearance.json", read("seed-clearance.json"), provenance),
    )
