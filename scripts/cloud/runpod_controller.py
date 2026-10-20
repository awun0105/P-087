"""Standalone reconciler / admin CLI. Disabled policy still reconciles existing owned Pods."""

import argparse
import json
import logging
import sqlite3
from threading import Event

from psycopg import Error as PostgresError

from src.config import get_settings
from src.services.orchestration.gpu.catalog import load_catalog
from src.services.orchestration.gpu.config import GpuSettings
from src.services.orchestration.gpu.controller import Controller
from src.services.orchestration.gpu.provider import RunPod, transport
from src.services.orchestration.gpu.state import StateStore
from src.services.orchestration.gpu.workload import inventory
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.projects.registry import get_project_registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "once", "status", "drain", "resume", "watchdog", "forget-unknown"])
    args = parser.parse_args(argv)
    policy, settings = GpuSettings(), get_settings()
    if not policy.deployment_id:
        parser.error("GPU_DEPLOYMENT_ID is required")
    store = StateStore(RuntimeDatabase(settings.database_url), policy.deployment_id)
    if args.action in {"drain", "resume"}:
        with store.locked() as (_, c, _):
            c.drain = args.action == "drain"
            if not c.drain:
                c.attempts, c.retry_at, c.error = 0, 0, ""
        return 0
    if args.action == "status":
        c = store.read()
        with store.database.transaction() as tx:
            total = sum(
                json.loads(row[0]).get("estimated_usd", 0)
                for row in tx.execute(
                    "SELECT payload FROM r2s_gpu_history WHERE deployment_id=?", (c.deployment,)
                ).fetchall()
            )
        # Explicit allowlist: never print boot token, worker env or connection URL.
        print(
            json.dumps(
                {
                    k: getattr(c, k)
                    for k in (
                        "state",
                        "intent",
                        "pod",
                        "profile",
                        "attempts",
                        "drain",
                        "error",
                        "estimated_usd",
                        "leader_until",
                    )
                }
            )
        )
        print(json.dumps({"project_estimated_usd": total, "phase_seconds": c.phase_seconds}))
        return 0
    if args.action == "watchdog":
        # Run on an independent host/scheduler; never provisions. Same DB gates and job protection.
        policy = policy.model_copy(update={"autoprov_enabled": False})
    if not policy.runpod_api_key or policy.release_catalog is None:
        parser.error("Provider key and pinned catalog required for reconciliation")
    catalog = load_catalog(policy.release_catalog)
    controller = Controller(
        store,
        policy,
        catalog,
        RunPod(transport(policy.runpod_api_key.get_secret_value())),
        # Read the controller's catalog at call time: it reloads the file when a new release is installed.
        lambda: inventory(settings, get_project_registry(), controller.catalog),
        catalog_path=policy.release_catalog,
    )
    logging.basicConfig(level=logging.INFO)
    if args.action == "forget-unknown":
        outcome = controller.forget_unknown()
        print(outcome)
        return 0 if outcome in {"forgotten", "nothing_to_forget"} else 1
    while True:
        try:
            outcome = controller.tick()
            logging.info("gpu_controller outcome=%s", outcome)
        except (PostgresError, sqlite3.Error, OSError):
            logging.error("gpu_controller outcome=database_unavailable")
            if args.action in {"once", "watchdog"}:
                return 1
            Event().wait(policy.poll_seconds)
            continue
        except Exception as error:  # noqa: BLE001 - supervisor restarts a failed control process
            logging.error("gpu_controller failed category=%s", type(error).__name__)
            return 1
        if args.action in {"once", "watchdog"}:
            return 0
        Event().wait(policy.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
