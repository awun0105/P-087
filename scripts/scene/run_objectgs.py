"""Run the prepared-input ObjectGS stage; no SceneIR publication or legacy fallback.

PYTHONPATH=. .venv/bin/python scripts/scene/run_objectgs.py --request request.json --result result.json
"""

import argparse
import json
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.services.scene.objectgs import PreparedObjectGSRequest as Request
from src.services.scene.objectgs import run_prepared_objectgs as run


def main() -> None:
    def terminated(signum: int, frame: object) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminated)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    if args.result.resolve() == args.request.resolve():
        raise ValueError("request and result paths must differ")
    request = Request.model_validate_json(args.request.read_bytes())
    args.result.unlink(missing_ok=True)
    receipt = run(request, progress=lambda stage: print(json.dumps({"stage": stage}), flush=True))
    args.result.write_text(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
