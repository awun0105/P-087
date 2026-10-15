"""Bind explicit instance masks to pinned upstream's existing TSDF alpha-mask hook."""

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    args, forwarded = parser.parse_known_args()
    path = args.upstream / "export_object_mesh.py"
    source = path.read_text()
    anchor = "    gaussExtractor.reconstruction(scene.getTrainCameras())"
    if source.count(anchor) != 1:
        raise RuntimeError("Pinned ObjectGS mesh export changed; revalidate the instance-mask adapter")
    source = source.replace(
        anchor,
        "    for camera in scene.getTrainCameras():\n"
        "        camera.alpha_mask = (camera.object_mask.cpu() == args.query_label_id).unsqueeze(0).float()\n" + anchor,
    )
    sys.path.insert(0, str(args.upstream))
    sys.argv = [str(path), *forwarded]
    exec(compile(source, str(path), "exec"), {"__name__": "__main__", "__file__": str(path)})


if __name__ == "__main__":
    main()
