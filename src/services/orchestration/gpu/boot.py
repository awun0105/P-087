"""Boot progress of a managed GPU pod, so the controller drops a pod that failed or stalled before registering.

The image entrypoint marks each step (`python -m src.services.orchestration.gpu.boot <step>`, `--failed` when the step
exits non-zero). Marks live under `workers["boot"]` of the control row, never as a new top-level field, so worker images
from an older release still parse the row. Marking never blocks or fails the boot itself.
"""

import argparse
import os
import sys
from urllib.parse import urlsplit, urlunsplit

from src.services.orchestration.gpu.state import StateStore
from src.services.orchestration.jobs.database import RuntimeDatabase

BOOT_KEY = "boot"


def mark(step: str, *, failed: bool = False) -> bool:
    """Record the current boot step of this pod; False when this pod is not the generation the controller is starting."""
    token, deployment = os.environ.get("GPU_BOOT_TOKEN", ""), os.environ.get("GPU_DEPLOYMENT_ID", "")
    url = os.environ.get("DATABASE_URL", "")
    if not token or not deployment or not url:
        return False
    parsed = urlsplit(url)
    main_url = urlunsplit(parsed._replace(fragment="")) if parsed.scheme in {"postgres", "postgresql"} else url
    with StateStore(RuntimeDatabase(main_url), deployment).locked() as (_, control, now):
        if control.boot_token != token or control.state != "starting":
            return False
        control.workers[BOOT_KEY] = {
            "step": step,
            "failed": failed,
            "at": now,
            "heartbeat": now,
            "ready": False,
            "busy": False,
        }
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step")
    parser.add_argument("--failed", action="store_true")
    args = parser.parse_args()
    try:
        mark(args.step, failed=args.failed)
    except Exception as error:  # noqa: BLE001 - a lost mark only delays detection; the boot must go on
        print(f"[!] Không ghi được mốc khởi động {args.step}: {type(error).__name__}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
