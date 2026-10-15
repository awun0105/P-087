"""CPU-only inspection/repair of a saved object-local metre mesh; never trains or edits a scene."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.services.scene.surface_mesh import load_support, load_surface, process_surface  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--voxel-size-m", type=float, required=True, help="actual export TSDF resolution, not a repair tuning knob"
    )
    parser.add_argument("--coordinate-frame", choices=["object_local"], required=True)
    parser.add_argument("--distance-unit", choices=["m"], required=True)
    parser.add_argument(
        "--expected-bounds", type=Path, help="JSON (2,3) bounds of immutable object-local source anchors"
    )
    parser.add_argument("--support", type=Path, help="saved world-frame calibrated rendered-depth support NPZ")
    parser.add_argument("--support-checksum")
    parser.add_argument("--source-pose", type=Path, help="Transform JSON: world_from_object for --support")
    args = parser.parse_args()
    if args.support and (not args.source_pose or not args.support_checksum):
        parser.error("depth support requires its checksum and explicit world_from_object pose")
    source = args.input.read_bytes()
    mesh = load_surface(args.input)
    support = None
    if args.support:
        from src.models.contracts.coordinates import Transform
        from src.services.simulation.colliders.carve import _rotation

        pose = Transform.model_validate_json(args.source_pose.read_bytes())
        if pose.parent_frame != "world":
            parser.error("support transform must map object-local to world")
        support = load_support(
            args.support,
            checksum=args.support_checksum,
            world_from_object_rotation=_rotation(pose.rotation_quaternion_xyzw),
            object_translation=np.asarray(pose.translation_xyz),
        )
    expected = np.asarray(json.loads(args.expected_bounds.read_text())) if args.expected_bounds else None
    result, quality, repair = process_surface(
        mesh, voxel_size_m=args.voxel_size_m, support=support, expected_bounds=expected
    )
    # Refuse to overwrite previous evidence or the saved input.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    payload = result.export(file_type="glb")
    (args.output_dir / "surface.glb").write_bytes(payload)
    quality.update(
        source_checksum="sha256:" + hashlib.sha256(source).hexdigest(),
        result_checksum="sha256:" + hashlib.sha256(payload).hexdigest(),
        metric_scale_verified_against_anchors=expected is not None,
    )
    repair.update(source_checksum=quality["source_checksum"], result_checksum=quality["result_checksum"])
    checksums = {}
    for name, report in (("quality.json", quality), ("repair.json", repair)):
        content = json.dumps(report, sort_keys=True, indent=2, allow_nan=False).encode()
        (args.output_dir / name).write_bytes(content)
        checksums[name] = "sha256:" + hashlib.sha256(content).hexdigest()
    checksums["surface.glb"] = quality["result_checksum"]
    (args.output_dir / "checksums.json").write_text(json.dumps(checksums, sort_keys=True, indent=2))
    print(json.dumps(dict(passed=quality["passed"], reasons=quality["reasons"], reports=str(args.output_dir))))
    return 0 if quality["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
