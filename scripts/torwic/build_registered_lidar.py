"""REC-07 offline CLI: checksum-bound raw scans → registered LiDAR + provenance."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pydantic import ValidationError  # noqa: E402

from scripts.torwic.prefusion_inputs import checksum, validate_inputs  # noqa: E402
from scripts.torwic.prefusion_models import PrefusionRequest, PrefusionSettings  # noqa: E402
from src.models.contracts.identity import canonical_content_checksum  # noqa: E402


def _manifest(request: PrefusionRequest, stats: dict, cloud: Path) -> dict:
    from scripts.torwic import prefusion_cloud

    uses_gt = request.pose_origin == "ground_truth"
    result = dict(
        schema_version="1.0",
        artifact_type="TorwicLiDARPreparation",
        request=request.model_dump(mode="json"),
        trajectory_gt_used_for_lidar_prefusion=uses_gt,
        assistance_class="GT-assisted" if uses_gt else "declared-poses",
        coordinate_status="UNVERIFIED",
        confirmed_rgb_alignment=False,
        output={"relative_path": "registered_lidar.ply", "checksum": checksum(cloud), **stats},
        runtime={"open3d": prefusion_cloud.o3d.__version__, "numpy": prefusion_cloud.np.__version__},
        code_checksums={
            name: checksum(Path(__file__).with_name(name))
            for name in (
                "build_registered_lidar.py",
                "prefusion_inputs.py",
                "prefusion_models.py",
                "prefusion_cloud.py",
            )
        },
    )
    result["manifest_checksum"] = "sha256:" + "0" * 64
    result["manifest_checksum"] = canonical_content_checksum(result, "manifest_checksum")
    return result


def _output(settings: PrefusionSettings) -> Path:
    root = settings.dataset_root.resolve()
    target = (root / settings.output_relative).resolve()
    if not target.is_relative_to(root / "derived") or target.exists():
        raise ValueError("output must be a new nonescaping derived attempt")
    return target


def run_prefusion(settings: PrefusionSettings, request: PrefusionRequest) -> dict:
    """Chỉ publish sau validation/roundtrip; failure không ghi success manifest."""
    from scripts.torwic.prefusion_cloud import fuse, write_cloud

    request = PrefusionRequest.model_validate(request.model_dump())
    target = _output(settings)
    poses = validate_inputs(settings.dataset_root, request)
    cloud, stats = fuse(settings.dataset_root, request, poses)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rec07-", dir=target.parent) as directory:
        stage = Path(directory)
        write_cloud(stage / "registered_lidar.ply", cloud)
        manifest = _manifest(request, stats, stage / "registered_lidar.ply")
        validate_inputs(settings.dataset_root, request)
        (stage / "preparation_manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        target.mkdir()
        for name in ("registered_lidar.ply", "preparation_manifest.json"):
            os.link(stage / name, target / name)
    return manifest


def main() -> int:
    """Stable CLI; lỗi không expose đường dẫn private qua traceback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-relative", required=True)
    args = parser.parse_args()
    try:
        settings = PrefusionSettings(dataset_root=args.dataset_root, output_relative=args.output_relative)
        request = PrefusionRequest.model_validate_json(args.request.read_text())
        manifest = run_prefusion(settings, request)
    except (ValidationError, ValueError, OSError, RuntimeError) as error:
        if os.environ.get("REC07_DEBUG"):
            import traceback

            traceback.print_exc()
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "error_type": type(error).__name__,
                    "action": "Check request, source checksums, poses, point budget and output attempt",
                }
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": "SUCCEEDED",
                "manifest_checksum": manifest["manifest_checksum"],
                "point_count": manifest["output"]["point_count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
