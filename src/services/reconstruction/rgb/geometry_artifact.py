"""Dựng shared `GeometryArtifact` từ attempt evidence của REC-05.

Report của adapter và clearance receipt đều là dữ liệu riêng của attempt; contract
canonical phải dựng lại từ chúng và để validator shared contract tự kiểm, để EX-SIM
không phải tin lời producer.
"""

from pydantic import Field

from src.models.contracts.artifacts import ArtifactUri, Checksum, ContractModel, Identifier
from src.models.contracts.coordinates import MetricScale, MetricScaleStatus, Transform
from src.models.contracts.manifests import StageId
from src.models.contracts.reconstruction import (
    CapsuleFootprint,
    DependencyOrigin,
    GeometryArtifact,
    PreprocessingDependency,
    PreprocessingProvenance,
    SeedDecision,
    VoxelGridSummary,
)
from src.services.reconstruction.alignment.transforms import validated_transform
from src.services.reconstruction.rgb.voxel import Vector3, world_from_native


class GeometryArtifactInput(ContractModel):
    """Input gom cho builder; tránh truyền năm tham số rời rạc."""

    job_id: Identifier
    artifact_uri: ArtifactUri
    artifact_checksum: Checksum
    clearance_checksum: Checksum
    source_master_checksum: Checksum
    report: dict = Field(description="Adapter qualification report của attempt")
    clearance_receipt: dict = Field(description="Nội dung seed-clearance.json đã publish")


def _canonical_bounds(native: dict) -> tuple[Vector3, Vector3]:
    """Bounds native Y-up sang canonical Z-up; min/max phải tính lại, không hoán đổi."""
    corners = [
        world_from_native((x, y, z))
        for x in (native["min"][0], native["max"][0])
        for y in (native["min"][1], native["max"][1])
        for z in (native["min"][2], native["max"][2])
    ]
    return (
        tuple(min(point[axis] for point in corners) for axis in range(3)),
        tuple(max(point[axis] for point in corners) for axis in range(3)),
    )


def _voxel_summary(native: dict) -> VoxelGridSummary:
    grid_low, grid_high = _canonical_bounds(native["gridBounds"])
    scene_low, scene_high = _canonical_bounds(native["sceneBounds"])
    return VoxelGridSummary(
        resolution_m=native["voxelResolution"],
        grid_bounds_min_xyz_m=grid_low,
        grid_bounds_max_xyz_m=grid_high,
        scene_bounds_min_xyz_m=scene_low,
        scene_bounds_max_xyz_m=scene_high,
    )


def _seed_decision(receipt: dict, clearance_checksum: str) -> SeedDecision:
    """Relocation phải hiện diện trong contract, không chỉ trong receipt của attempt."""
    return SeedDecision(
        requested_world_m=tuple(receipt["requested_seed_world"]),
        accepted_world_m=tuple(receipt["accepted_seed_world"]),
        relocates=receipt["relocates"],
        relocation_distance_m=receipt["relocation_distance_m"],
        relocation_bound_m=receipt["relocation_bound_m"],
        occupancy_checksum=receipt["occupancy_binary_checksum"],
        clearance_evidence_checksum=clearance_checksum,
    )


def _provenance(source_master: str, confirmation: str) -> PreprocessingProvenance:
    """Visual là reconstruction ước lượng; metric anchor là ngoài, không dẫn xuất từ dữ liệu."""
    return PreprocessingProvenance(
        dependencies=[
            PreprocessingDependency(
                role="source_visual_master", origin=DependencyOrigin.ESTIMATED, source_checksum=source_master
            ),
            PreprocessingDependency(
                role="metric_confirmation", origin=DependencyOrigin.EXTERNAL, source_checksum=confirmation
            ),
        ],
        ground_truth_assisted=False,
    )


def _capsule(report: dict) -> CapsuleFootprint:
    config = report["config"]
    height, radius = config["capsule_height_m"], config["capsule_radius_m"]
    return CapsuleFootprint(height_m=height, radius_m=radius, length_m=max(0.0, height - 2 * radius))


def _rigid_transform(applied: dict) -> Transform:
    """Similarity đã scale thẳng vào geometry, nên contract chỉ giữ phần rigid + `MetricScale`.

    Dùng `validated_transform` của repo để không tái lập quy tắc finite/normalise quaternion.
    """
    return validated_transform(
        Transform(
            parent_frame=applied["target_frame"],
            local_frame=applied["source_frame"],
            translation_xyz=tuple(applied["translation_m"]),
            rotation_quaternion_xyzw=tuple(applied["rotation_xyzw"]),
        )
    )


def build_geometry_artifact(
    payload: GeometryArtifactInput,
) -> GeometryArtifact:
    """Contract canonical cho EX-SIM; metric/seed/ground-truth do validator shared enforce."""
    report = payload.report
    return GeometryArtifact(
        artifact_type="GeometryArtifact",
        schema_version="1.0",
        artifact_uri=payload.artifact_uri,
        artifact_checksum=payload.artifact_checksum,
        producer_stage=StageId.RGB_GEOMETRY,
        job_id=payload.job_id,
        source_modality="rgb_3dgs",
        geometry_format="glb",
        coordinate_system=report["coordinate_system"],
        metric_scale=MetricScale(status=MetricScaleStatus.CONFIRMED, meters_per_unit=report["scale_applied"]),
        applied_confirmation_checksum=report["applied_confirmation_checksum"],
        applied_transform=_rigid_transform(report["applied_transform"]),
        source_master_checksum=payload.source_master_checksum,
        voxel=_voxel_summary(report["native_voxel_metadata"]),
        seed=_seed_decision(payload.clearance_receipt, payload.clearance_checksum),
        capsule=_capsule(report),
        provenance=_provenance(payload.source_master_checksum, report["applied_confirmation_checksum"]),
    )
