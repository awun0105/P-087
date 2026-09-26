"""SplatTransform collision pipeline; entrypoint hiện chỉ dành cho synthetic proof.

REC-06 chưa có confirmed-record producer. Không expose product metric entrypoint,
không gán CONFIRMED và không publish GeometryArtifact từ fixture qualification.
"""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Literal

from src.models.contracts.artifacts import Checksum, ContractModel
from src.models.contracts.coordinates import CoordinateSystem
from src.services.reconstruction.adapters.collision_glb import canonicalize_collision, topology
from src.services.reconstruction.adapters.gaussian_scale import scale_gaussian_ply
from src.services.reconstruction.adapters.voxel_output import validate_voxel_output, write_evidence
from src.services.reconstruction.adapters.voxel_runtime import GeometryError, VoxelProcess, require_carve
from src.services.reconstruction.rgb.metric_models import MetricConfirmation
from src.services.reconstruction.rgb.voxel import VoxelConfig, cluster_command, collision_command, native_from_world

EVIDENCE_FILES = (
    "input.ply",
    "cluster.ply",
    "inspection.json",
    "cluster-inspection.json",
    "geometry.voxel.json",
    "geometry.voxel.bin",
    "geometry.collision.glb",
    "collision.glb",
    "version.log",
    "help.log",
    "inspect.log",
    "inspect-cluster.log",
    "node.log",
    "gpus.log",
    "cluster.log",
    "collision.log",
)


def _coordinate_evidence(config: VoxelConfig, scale_applied: float = 1.0) -> dict:
    return dict(
        coordinate_system=CoordinateSystem().model_dump(mode="json"),
        native_coordinate_system=dict(unit="meter", up_axis="Y", handedness="right"),
        native_from_world="R_x(-90deg)",
        world_from_native="R_x(+90deg)",
        scale_applied=scale_applied,
        native_navigation_seed=list(native_from_world(config.navigation_seed_world)),
        native_cluster_seed=list(native_from_world(config.cluster_seed_world)),
    )


def _gaussian_counts(workspace: Path) -> dict[str, int]:
    counts = {}
    for key, filename in (("input", "inspection.json"), ("cluster", "cluster-inspection.json")):
        counts[key] = json.loads((workspace / filename).read_text())["info"]["numGaussians"]
    if not 0 < counts["cluster"] <= counts["input"]:
        raise GeometryError("Invalid Gaussian count after cluster filtering")
    return counts


def file_checksum(path: Path) -> str:
    """Hash streaming để không giữ thêm toàn bộ Gaussian payload trong RAM."""
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


class SyntheticVoxelRequest(ContractModel):
    """Input test đã biết kích thước; tuyệt đối không dùng thay metric confirmation."""

    evidence_kind: Literal["synthetic_known_dimensions"] = "synthetic_known_dimensions"
    source: Path
    source_checksum: Checksum
    config: VoxelConfig


class ProductVoxelRequest(ContractModel):
    """Product voxelization request ràng buộc chặt chẽ với confirmed metric record."""

    confirmation: MetricConfirmation
    source: Path
    source_checksum: Checksum
    config: VoxelConfig
    applied_record_checksum: Checksum | None = None


class SplatTransformVoxelAdapter:
    """Reuse upstream filtering/voxel/carve/mesher, giữ isolated immutable attempts."""

    def __init__(self, process: VoxelProcess) -> None:
        self.process = process

    def run_synthetic(self, request: SyntheticVoxelRequest, workspace: Path) -> dict:
        """Technical proof duy nhất; product metric gate chờ handoff của REC-06."""
        request = SyntheticVoxelRequest.model_validate(request.model_dump())
        if file_checksum(request.source) != request.source_checksum:
            raise GeometryError("Synthetic source checksum mismatch")
        return self._execute(request, workspace)

    def run_product(self, request: ProductVoxelRequest, workspace: Path) -> dict:
        """Product metric voxelization ràng buộc chặt chẽ với REC-06 confirmation."""
        request = ProductVoxelRequest.model_validate(request.model_dump())
        if request.applied_record_checksum is not None:
            raise ValueError("metric transform already applied; refusing double scaling")
        if request.confirmation.status != "CONFIRMED":
            raise ValueError("metric confirmation must be CONFIRMED")
        if file_checksum(request.source) != request.source_checksum:
            raise GeometryError("Product source checksum mismatch")
        return self._execute(request, workspace)

    def _execute(self, request: SyntheticVoxelRequest | ProductVoxelRequest, workspace: Path) -> dict:
        workspace.mkdir(parents=True, exist_ok=False)
        try:
            shutil.copyfile(request.source, workspace / "input.ply")
            if file_checksum(workspace / "input.ply") != request.source_checksum:
                raise GeometryError("Copied source checksum mismatch")
            if isinstance(request, ProductVoxelRequest):
                scale = request.confirmation.preview.transform.scale_m_per_sfm_unit
                if abs(scale - 1.0) >= 1e-9:
                    scale_gaussian_ply(workspace / "input.ply", workspace / "input.ply", scale)
            self._pipeline(request.config, workspace)
            report = self._report(request, workspace)
            if file_checksum(request.source) != request.source_checksum:
                raise GeometryError("Source changed during voxel attempt")
            write_evidence(workspace / "qualification.json", report)
            return report
        except (OSError, ValueError) as error:
            raise GeometryError("Voxel attempt failed; inspect private logs; no artifact published") from error

    def _pipeline(self, config: VoxelConfig, workspace: Path) -> None:
        self.process.qualify(workspace)
        script = Path(__file__).with_name("voxel_inspect.mjs").resolve()
        module = self.process.settings.module_path.resolve()
        self.process.run((str(script), str(module)), (workspace, "inspect"))
        self.process.cli(cluster_command(config), (workspace, "cluster"))
        if not (workspace / "cluster.ply").is_file():
            raise GeometryError("Cluster output missing")
        self.process.run(
            (str(script), str(module), "cluster.ply", "cluster-inspection.json"), (workspace, "inspect-cluster")
        )
        output = self.process.cli(collision_command(config), (workspace, "collision"))
        require_carve(output)

    def _report(self, request: SyntheticVoxelRequest | ProductVoxelRequest, workspace: Path) -> dict:
        metadata = validate_voxel_output(workspace, request.config)
        mesh = canonicalize_collision(workspace / "geometry.collision.glb", workspace / "collision.glb")
        is_prod = isinstance(request, ProductVoxelRequest)
        evidence_kind = request.confirmation.preview.request.evidence_kind if is_prod else request.evidence_kind
        scale_applied = request.confirmation.preview.transform.scale_m_per_sfm_unit if is_prod else 1.0
        applied_checksum = request.confirmation.record_checksum if is_prod else None
        return dict(
            schema_version="1.0",
            evidence_kind=evidence_kind,
            product_artifact_published=False,
            applied_confirmation_checksum=applied_checksum,
            runtime="splat-transform v3.6.6 (afbc281)",
            source_checksum=request.source_checksum,
            config=request.config.model_dump(mode="json"),
            config_checksum=request.config.checksum(),
            gaussian_counts=_gaussian_counts(workspace),
            **_coordinate_evidence(request.config, scale_applied),
            native_voxel_metadata=metadata.model_dump(mode="json", by_alias=True),
            topology=topology(mesh),
            canonical_bounds=dict(
                min=[min(p[i] for p in mesh.positions) for i in range(3)],
                max=[max(p[i] for p in mesh.positions) for i in range(3)],
            ),
            files={name: file_checksum(workspace / name) for name in EVIDENCE_FILES},
        )
