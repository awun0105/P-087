"""Pack, verify, publish or provision an immutable interactive-demo library."""

import argparse
import json
from pathlib import Path

from src.config import Settings
from src.services.orchestration.samples.release import (
    bootstrap_library,
    pack_library,
    publish_library,
    verify_archive,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack")
    pack.add_argument("--library", type=Path, default=Path("data/demo/library"))
    pack.add_argument("--out", type=Path, required=True)
    pack.add_argument("--release", required=True)
    pack.add_argument("--sample", action="append", default=[])
    for name in ("verify", "publish"):
        command = commands.add_parser(name)
        command.add_argument("package", type=Path)
    commands.add_parser("bootstrap")
    args = parser.parse_args()
    if args.command == "pack":
        result = pack_library(args.library, args.out, args.release, args.sample)
    elif args.command == "verify":
        manifest = verify_archive(args.package)
        result = {"release_id": manifest["release_id"], "samples": manifest["samples"], "files": len(manifest["files"])}
    elif args.command == "publish":
        result = publish_library(Settings(_env_file=args.env_file), args.package)
    else:
        bootstrap_library(Settings(_env_file=args.env_file))
        result = {"status": "provisioned"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
