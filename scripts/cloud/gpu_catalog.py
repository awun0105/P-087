"""Seal operator-qualified release metadata; never rents a GPU or invents qualification."""

import argparse
import json
from pathlib import Path

from src.services.orchestration.gpu.catalog import ReleaseCatalog, seal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Release metadata JSON with profiles and optional input_registry")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = seal(json.loads(args.source.read_bytes()))
    ReleaseCatalog.model_validate(payload)
    # Refuse accidental mutation of a pinned release.
    with args.out.open("x") as target:
        target.write(json.dumps(payload, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
