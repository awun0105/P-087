"""Manual real-tool qualification cho REC-07: gộp PCD thật thành registered_lidar.ply."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from scripts.torwic.build_registered_lidar import run_prefusion
from scripts.torwic.prefusion_inputs import checksum
from scripts.torwic.prefusion_models import (
    PrefusionRequest,
    PrefusionSettings,
    ScanSource,
    SourceFile,
)
from src.models.contracts.reconstruction import DependencyOrigin


class SmokeSettings(BaseSettings):
    """Cấu hình chạy smoke trên lát cắt 5 scan của Aisle_CW."""

    dataset_root: Path = Path("data/torwic_slam")
    output_relative: str = "derived/aisle_cw/rec07_smoke_sub100_104"
    start_frame: int = 100
    frame_count: int = 5
    voxel_size_m: float = 0.05
    model_config = SettingsConfigDict(env_prefix="REC07_SMOKE_", extra="forbid")


def run_smoke(settings: SmokeSettings) -> dict:
    """Tạo request thực tế và chạy prefusion qua Open3D."""
    root = settings.dataset_root.resolve()
    scans = []
    for frame_id in range(settings.start_frame, settings.start_frame + settings.frame_count):
        rel = f"raw/traversals/aisle_cw/lidar/{frame_id:06d}.pcd"
        scans.append(ScanSource(frame_id=frame_id, relative_path=rel, checksum=checksum(root / rel)))

    traj_rel = "raw/traversals/aisle_cw/traj_gt.txt"
    times_rel = "raw/traversals/aisle_cw/frame_times.txt"
    calib_rel = "raw/global/calibrations.txt"
    coord_rel = "normalized/aisle_cw/coordinate_metadata.json"

    request = PrefusionRequest(
        traversal_id="aisle_cw",
        scans=scans,
        trajectory=SourceFile(relative_path=traj_rel, checksum=checksum(root / traj_rel)),
        timestamps=SourceFile(relative_path=times_rel, checksum=checksum(root / times_rel)),
        calibration=SourceFile(relative_path=calib_rel, checksum=checksum(root / calib_rel)),
        coordinate_evidence=SourceFile(relative_path=coord_rel, checksum=checksum(root / coord_rel)),
        pose_origin=DependencyOrigin.GROUND_TRUTH,
        allow_ground_truth_poses=True,
        source_frame="os_sensor",
        target_frame="world",
        unit="meter",
        transform_semantics="target_from_source",
        timestamp_tolerance_s=0.01,
        quaternion_norm_tolerance=0.001,
        voxel_size_m=settings.voxel_size_m,
        min_range_m=0.5,
        max_range_m=50.0,
        max_scan_points=300000,
        max_merged_points=1000000,
    )

    pref_settings = PrefusionSettings(dataset_root=root, output_relative=settings.output_relative)
    return run_prefusion(pref_settings, request)


def main() -> None:
    settings = SmokeSettings()
    target = settings.dataset_root / settings.output_relative
    if target.exists():
        print(f"Target {target} already exists, skipping execution.")
        return

    manifest = run_smoke(settings)
    print("REC-07 Smoke SUCCEEDED:")
    print(f"  Manifest checksum: {manifest['manifest_checksum']}")
    print(f"  Point count: {manifest['output']['point_count']}")
    print(f"  Bounds min: {manifest['output']['bounds_min']}")
    print(f"  Bounds max: {manifest['output']['bounds_max']}")


if __name__ == "__main__":
    main()
