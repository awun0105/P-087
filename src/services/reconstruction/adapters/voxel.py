"""SplatTransform voxel/collision process; authority thuộc RgbGeometryService.

Synthetic proof tách product record-bound derivative; adapter không tự cấp
confirmation, không tự publish shared artifact hay nghiệm thu capsule an toàn.
"""

import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Literal

from src.models.contracts.artifacts import Checksum, ContractModel
from src.models.contracts.coordinates import CoordinateSystem
from src.models.contracts.reconstruction import GeometryStatisticalFilterEvidence
from src.services.reconstruction.adapters.collision_glb import canonicalize_collision, degenerate_removed, topology
from src.services.reconstruction.adapters.gaussian_outlier_filter import filter_gaussian_ply
from src.services.reconstruction.adapters.gaussian_scale import (
    GaussianTransformRequest,
    SplatTransformSimilarityAdapter,
)
from src.services.reconstruction.adapters.voxel_clearance import validate_seed_clearance
from src.services.reconstruction.adapters.voxel_output import validate_voxel_output, write_evidence
from src.services.reconstruction.adapters.voxel_runtime import (
    GeometryError,
    VoxelProcess,
    require_carve,
    require_external_fill,
)
from src.services.reconstruction.rgb.canonical.metric_models import MetricConfirmation
from src.services.reconstruction.rgb.geometry.voxel import (
    VoxelConfig,
    cluster_command,
    collision_command,
    native_from_world,
    occupancy_command,
    require_voxel_capacity,
)

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
    "occupancy.log",
    "occupancy.voxel.json",
    "occupancy.voxel.bin",
    "seed-clearance.json",
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
        if request.source_checksum != request.confirmation.preview.request.anchor.source_master.artifact_checksum:
            raise ValueError("voxel source is not the master bound to metric confirmation")
        if file_checksum(request.source) != request.source_checksum:
            raise GeometryError("Product source checksum mismatch")
        return self._execute(request, workspace)

    def _execute(self, request: SyntheticVoxelRequest | ProductVoxelRequest, workspace: Path) -> dict:
        workspace.mkdir(parents=True, exist_ok=False)
        try:
            self._prepare_input(request, workspace)
            self._pipeline(request.config, workspace)
            report = self._report(request, workspace)
            if file_checksum(request.source) != request.source_checksum:
                raise GeometryError("Source changed during voxel attempt")
            write_evidence(workspace / "qualification.json", report)
            return report
        except (OSError, ValueError) as error:
            raise GeometryError("Voxel attempt failed; inspect private logs; no artifact published") from error

    def _prepare_input(self, request: SyntheticVoxelRequest | ProductVoxelRequest, workspace: Path) -> None:
        if isinstance(request, ProductVoxelRequest):
            transform = GaussianTransformRequest(
                source=request.source,
                source_checksum=request.source_checksum,
                transform=request.confirmation.preview.transform,
            )
            SplatTransformSimilarityAdapter(self.process).transform(transform, workspace / "metric")
            shutil.copyfile(workspace / "metric/input.ply", workspace / "input.ply")
        else:
            shutil.copyfile(request.source, workspace / "input.ply")
            if file_checksum(workspace / "input.ply") != request.source_checksum:
                raise GeometryError("Copied source checksum mismatch")

    def _pipeline(self, config: VoxelConfig, workspace: Path) -> None:
        self.process.qualify(workspace)
        if config.external_fill_size_m is not None:
            if "--voxel-external-fill" not in (workspace / "help.log").read_text():
                raise GeometryError("Geometry CLI lacks --voxel-external-fill")
        if config.floor_fill_size_m is not None:
            if "--voxel-floor-fill" not in (workspace / "help.log").read_text():
                raise GeometryError("Geometry CLI lacks --voxel-floor-fill")
        script = Path(__file__).with_name("voxel_inspect.mjs").resolve()
        module = self.process.settings.module_path.resolve()
        self.process.run((str(script), str(module)), (workspace, "inspect"))
        cluster_input = "input.ply"
        if config.statistical_outlier_removal is not None:
            filtered_input = workspace / "statistical-filtered-input.ply"
            filter_evidence = filter_gaussian_ply(
                workspace / "input.ply", filtered_input, config.statistical_outlier_removal
            )
            write_evidence(workspace / "statistical-outlier.json", filter_evidence.model_dump(mode="json"))
            cluster_input = filtered_input.name
        self.process.cli(cluster_command(config, input_filename=cluster_input), (workspace, "cluster"))
        if not (workspace / "cluster.ply").is_file():
            raise GeometryError("Cluster output missing")
        self.process.run(
            (str(script), str(module), "cluster.ply", "cluster-inspection.json"), (workspace, "inspect-cluster")
        )
        cluster_checksum = file_checksum(workspace / "cluster.ply")
        if config.external_fill_size_m is not None or config.floor_fill_size_m is not None:
            _require_cluster_capacity(workspace, config)
        occupancy_log = self.process.cli(occupancy_command(config), (workspace, "occupancy"))
        if config.external_fill_size_m is not None:
            require_external_fill(occupancy_log)
        clearance = validate_seed_clearance(workspace, config)
        carve_config = VoxelConfig.model_validate(
            config.model_dump() | {"navigation_seed_world": clearance["accepted_seed_world"]}
        )
        output = self.process.cli(collision_command(carve_config), (workspace, "collision"))
        if config.external_fill_size_m is not None:
            require_external_fill(output)
        require_carve(output)
        if file_checksum(workspace / "cluster.ply") != cluster_checksum:
            raise GeometryError("Cluster changed during occupancy/carve attempt")

    def _report(self, request: SyntheticVoxelRequest | ProductVoxelRequest, workspace: Path) -> dict:
        metadata = validate_voxel_output(workspace, request.config)
        mesh = canonicalize_collision(workspace / "geometry.collision.glb", workspace / "collision.glb")
        is_prod = isinstance(request, ProductVoxelRequest)
        evidence_kind = request.confirmation.preview.request.evidence_kind if is_prod else request.evidence_kind
        scale_applied = request.confirmation.preview.transform.scale_m_per_sfm_unit if is_prod else 1.0
        applied_checksum = request.confirmation.record_checksum if is_prod else None
        accepted_seed = json.loads((workspace / "seed-clearance.json").read_text())["accepted_seed_world"]
        gaussian_counts = _gaussian_counts(workspace)
        statistical_filter_evidence = None
        if request.config.statistical_outlier_removal is not None:
            statistical_filter_evidence = GeometryStatisticalFilterEvidence.model_validate(
                json.loads((workspace / "statistical-outlier.json").read_text())
            )
            if statistical_filter_evidence.input_gaussian_count != gaussian_counts["input"]:
                raise GeometryError("SOR input count differs from the upstream metric inspection")
            if statistical_filter_evidence.retained_gaussian_count < gaussian_counts["cluster"]:
                raise GeometryError("Cluster output contains more Gaussians than the SOR input")
        return dict(
            schema_version="1.0",
            evidence_kind=evidence_kind,
            product_artifact_published=False,
            applied_confirmation_checksum=applied_checksum,
            applied_transform=request.confirmation.preview.transform.model_dump(mode="json") if is_prod else None,
            runtime="splat-transform v3.6.6 (afbc281)",
            source_checksum=request.source_checksum,
            config=request.config.model_dump(mode="json"),
            config_checksum=request.config.checksum(),
            external_fill={
                "status": "applied" if request.config.external_fill_size_m is not None else "disabled",
                "size_m": request.config.external_fill_size_m,
                "occupancy_log_checksum": file_checksum(workspace / "occupancy.log"),
                "collision_log_checksum": file_checksum(workspace / "collision.log"),
            },
            accepted_navigation_seed=accepted_seed,
            native_accepted_navigation_seed=list(native_from_world(accepted_seed)),
            gaussian_counts=gaussian_counts,
            **_coordinate_evidence(request.config, scale_applied),
            native_voxel_metadata=metadata.model_dump(mode="json", by_alias=True),
            topology=topology(mesh),
            degenerate_triangles_removed=degenerate_removed(workspace / "geometry.collision.glb"),
            statistical_filter_evidence=(
                statistical_filter_evidence.model_dump(mode="json") if statistical_filter_evidence is not None else None
            ),
            canonical_bounds=dict(
                min=[min(p[i] for p in mesh.positions) for i in range(3)],
                max=[max(p[i] for p in mesh.positions) for i in range(3)],
            ),
            files={name: file_checksum(workspace / name) for name in _evidence_files(is_prod, request.config)},
        )


def _require_cluster_capacity(workspace: Path, config: VoxelConfig) -> None:
    """Conservative bounds from upstream stats; rotations cannot exceed the scale-vector norm."""
    fill_sizes = [value for value in (config.external_fill_size_m, config.floor_fill_size_m) if value is not None]
    if not fill_sizes:
        return
    # Floor fill pads only X/Z. Bounding all axes by the larger radius is conservative.
    fill_size = max(fill_sizes)
    try:
        lod = json.loads((workspace / "cluster-inspection.json").read_text())["stats"]["lods"][0]
        columns, data = lod["columns"], lod["data"]
        scale_logs = [data["max"][columns.index(f"scale_{axis}")] for axis in range(3)]
        position_bounds = [
            (data["min"][columns.index(axis)], data["max"][columns.index(axis)]) for axis in ("x", "y", "z")
        ]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise GeometryError("Missing Gaussian statistics for padded voxel capacity") from error
    if not all(isinstance(value, int | float) and math.isfinite(value) for value in scale_logs):
        raise GeometryError("Missing finite Gaussian scales for voxel capacity")
    # SIGMA_CUTOFF=3 in the qualified 3.6.6 writer; hypot avoids squaring overflow.
    try:
        halo = 3 * math.hypot(*(math.exp(value) for value in scale_logs))
    except OverflowError as error:
        raise GeometryError("Gaussian extents exceed voxel capacity") from error
    if not all(isinstance(value, int | float) and math.isfinite(value) for pair in position_bounds for value in pair):
        raise GeometryError("Missing finite Gaussian positions for voxel capacity")
    lengths = tuple(high - low + 2 * halo for low, high in position_bounds)
    require_voxel_capacity(lengths, config.resolution_m, fill_size)


def _evidence_files(is_product: bool, config: VoxelConfig) -> tuple[str, ...]:
    metric_files = (
        "source.ply",
        "input.ply",
        "metric-transform.json",
        "metric-transform-receipt.json",
        "metric-derivative.json",
        "metric-transform.log",
    )
    evidence = EVIDENCE_FILES
    if config.statistical_outlier_removal is not None:
        evidence += ("statistical-filtered-input.ply", "statistical-outlier.json")
    return evidence + tuple("metric/" + name for name in metric_files) if is_product else evidence
