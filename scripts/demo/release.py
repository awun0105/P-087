"""Pack, verify, publish, import or provision the interactive-demo library (catalog + object store)."""

import argparse
import json
from pathlib import Path

from src.config import Settings
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.samples.catalog import DemoCatalog, import_library, prepare_library
from src.services.orchestration.samples.release import (
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
    commands.add_parser("bootstrap", help="seed from the pinned archive once, import disk bundles, verify and repair")
    commands.add_parser("import", help="register bundles copied by hand into PRODUCT_DEMO_DIR (catalog + object store)")
    args = parser.parse_args()
    if args.command == "pack":
        result = pack_library(args.library, args.out, args.release, args.sample)
    elif args.command == "verify":
        manifest = verify_archive(args.package)
        result = {"release_id": manifest["release_id"], "samples": manifest["samples"], "files": len(manifest["files"])}
    elif args.command == "publish":
        result = publish_library(Settings(_env_file=args.env_file), args.package)
    elif args.command == "import":
        settings = Settings(_env_file=args.env_file)
        result = {"imported": import_library(settings, DemoCatalog(RuntimeDatabase(settings.database_url)))}
    else:
        settings = Settings(_env_file=args.env_file)
        result = prepare_library(settings, RuntimeDatabase(settings.database_url)).model_dump()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
