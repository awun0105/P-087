"""Render the API env for an off-VM GPU watchdog run (GitHub Actions or any independent host).

Reads the production API env file, rewrites container paths (/app/...) to a local checkout and scratch
directory, points the GPU catalog at a local copy, and drops settings the watchdog never uses
(worker env, controller supervision). The watchdog itself never provisions: `runpod_controller watchdog`
forces autoprovisioning off and only reconciles or terminates pods this deployment already owns.

    python -m scripts.cloud.watchdog_env --api-env api.env --catalog gpu-catalog.json \
        --checkout . --scratch /tmp/r2s-watchdog --out watchdog.env
"""

import argparse
from pathlib import Path

from dotenv import dotenv_values

DROP = frozenset({"GPU_WORKER_ENV_FILE", "GPU_CONTROLLER_RUN", "PRODUCT_INPUT_RUNTIME_REGISTRY"})


def render(api_env: dict[str, str | None], catalog: Path, checkout: Path, scratch: Path) -> dict[str, str]:
    """Pure transform so it can be tested without files or secrets."""
    out: dict[str, str] = {}
    for key, value in api_env.items():
        if value is None or key in DROP:
            continue
        if value.startswith("/app/data"):
            value = str(scratch / "data") + value.removeprefix("/app/data")
        elif value.startswith("/app/"):
            value = str(checkout) + value.removeprefix("/app")
        out[key] = value
    out["GPU_RELEASE_CATALOG"] = out["PRODUCT_GPU_RELEASE_CATALOG"] = str(catalog)
    out["GPU_AUTOPROVISION_ENABLED"] = "false"
    out["PRODUCT_DEMO_REQUIRED"] = "false"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-env", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    values = render(
        dotenv_values(args.api_env), args.catalog.resolve(), args.checkout.resolve(), args.scratch.resolve()
    )
    for key in ("ARTIFACT_ROOT", "PRODUCT_WORKER_ROOT", "PRODUCT_TRASH_ROOT", "PRODUCT_DEMO_DIR"):
        if key in values:
            Path(values[key]).mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    args.out.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
