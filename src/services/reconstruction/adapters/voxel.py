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
from src.services.reconstruction.adapters.voxel_output import validate_voxel_output, write_evidence
from src.services.reconstruction.adapters.voxel_runtime import GeometryError, VoxelProcess, require_carve
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


def _coordinate_evidence(config: VoxelConfig) -> dict:
    return dict(
        coordinate_system=CoordinateSystem().model_dump(mode="json"),
        native_coordinate_system=dict(unit="meter", up_axis="Y", handedness="right"),
        native_from_world="R_x(-90deg)",
        world_from_native="R_x(+90deg)",
        scale_applied=1.0,
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


class SplatTransformVoxelAdapter:
    """Reuse upstream filtering/voxel/carve/mesher, giữ isolated immutable attempts."""

    def __init__(self, process: VoxelProcess) -> None:
        self.process = process

    def run_synthetic(self, request: SyntheticVoxelRequest, workspace: Path) -> dict:
        """Technical proof duy nhất; product metric gate chờ handoff của REC-06."""
        request = SyntheticVoxelRequest.model_validate(request.model_dump())
        if file_checksum(request.source) != request.source_checksum:
            raise GeometryError("Synthetic source checksum mismatch")
        workspace.mkdir(parents=True, exist_ok=False)
        try:
            shutil.copyfile(request.source, workspace / "input.ply")
            if file_checksum(workspace / "input.ply") != request.source_checksum:
                raise GeometryError("Copied source checksum mismatch")
            self._pipeline(request.config, workspace)
            report = self._report(request, workspace)
            if file_checksum(request.source) != request.source_checksum:
                raise GeometryError("Source changed during voxel attempt")
            write_evidence(workspace / "qualification.json", report)
            return report
        except (OSError, ValueError) as error:
            raise GeometryError(
                "Synthetic voxel attempt failed; inspect private logs; no artifact published"
            ) from error

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

    def _report(self, request: SyntheticVoxelRequest, workspace: Path) -> dict:
        metadata = validate_voxel_output(workspace, request.config)
        mesh = canonicalize_collision(workspace / "geometry.collision.glb", workspace / "collision.glb")
        return dict(
            schema_version="1.0",
            evidence_kind=request.evidence_kind,
            product_artifact_published=False,
            runtime="splat-transform v3.6.6 (afbc281)",
            source_checksum=request.source_checksum,
            config=request.config.model_dump(mode="json"),
            config_checksum=request.config.checksum(),
            gaussian_counts=_gaussian_counts(workspace),
            **_coordinate_evidence(request.config),
            native_voxel_metadata=metadata.model_dump(mode="json", by_alias=True),
            topology=topology(mesh),
            canonical_bounds=dict(
                min=[min(p[i] for p in mesh.positions) for i in range(3)],
                max=[max(p[i] for p in mesh.positions) for i in range(3)],
            ),
            files={name: file_checksum(workspace / name) for name in EVIDENCE_FILES},
        )
