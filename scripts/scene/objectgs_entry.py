"""Run pinned upstream training without its import-time global GPU auto-selection."""

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--scene-name", required=True)
    args = parser.parse_args()
    path = args.upstream / "train.py"
    source = path.read_text()
    prelude = """import subprocess
cmd = 'nvidia-smi -q -d Memory |grep -A4 GPU|grep Used'
result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE).stdout.decode().split('\\n')
os.environ['CUDA_VISIBLE_DEVICES']=str(np.argmin([int(x.split()[2]) for x in result[:-1]]))"""
    if source.count(prelude) != 1:
        raise RuntimeError("Pinned ObjectGS GPU-selection prelude changed; revalidate the runtime adapter")
    source = source.replace(
        prelude, "# GPU visibility is set explicitly by the host process runner." + "\n" * prelude.count("\n")
    )
    sys.path.insert(0, str(args.upstream))
    sys.argv = [str(path), "--config", str(args.config), "--scene_name", args.scene_name]
    exec(compile(source, str(path), "exec"), {"__name__": "__main__", "__file__": str(path)})


if __name__ == "__main__":
    main()
