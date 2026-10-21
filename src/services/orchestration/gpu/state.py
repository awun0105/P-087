"""Control state uses the main schema, including from disposable scoped workers."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.services.orchestration.jobs.database import RuntimeDatabase, RuntimeTransaction


@dataclass
class Control:
    deployment: str
    state: str = "absent"
    version: int = 0
    owner: str = ""
    leader_until: float = 0
    intent: str = ""
    pod: str = ""
    profile: str = ""
    profile_payload: dict = field(default_factory=dict)
    idle_since: float | None = None
    created_at: float = 0
    attempts: int = 0
    #: Lần liên tiếp RunPod hết máy hợp lệ: chỉ để giãn thời gian thử lại, không tính vào `attempts` và không dừng thuê.
    inventory_misses: int = 0
    retry_at: float = 0
    drain: bool = False
    error: str = ""
    rate: float = 0
    estimated_usd: float = 0
    boot_token: str = ""
    workers: dict[str, dict] = field(default_factory=dict)
    phase_since: float = 0
    phase_seconds: dict[str, float] = field(default_factory=dict)


#: Fields added after the oldest worker image still in a release catalog, with their defaults. Older images build
#: `Control(**payload)` from the row and crash on a key they do not know (2026-10-21: every v5 pod failed to register
#: once the controller wrote `inventory_misses`), so these are written only when they differ from the default.
_LATE_FIELDS = {"inventory_misses": 0}


def control_payload(control: Control) -> dict:
    return {
        key: value for key, value in control.__dict__.items() if key not in _LATE_FIELDS or value != _LATE_FIELDS[key]
    }


def load_control(raw: dict) -> Control:
    """Ignore keys written by a newer controller, so this worker keeps working across a release."""
    return Control(**{key: value for key, value in raw.items() if key in Control.__dataclass_fields__})


def table(tx: RuntimeTransaction, name: str) -> str:
    return f"public.{name}" if tx.postgres else name


def db_time(tx: RuntimeTransaction) -> float:
    if tx.postgres:
        return float(tx.execute("SELECT EXTRACT(EPOCH FROM clock_timestamp())").fetchone()[0])
    return datetime.now(UTC).timestamp()


class StateStore:
    def __init__(self, database: RuntimeDatabase, deployment: str) -> None:
        if database.scope:
            raise ValueError("GPU controller requires main database")
        self.database, self.deployment = database, deployment

    @contextmanager
    def locked(self) -> Iterator[tuple[RuntimeTransaction, Control, float]]:
        with self.database.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO r2s_gpu_control(deployment_id,payload) VALUES (?,?) ON CONFLICT(deployment_id) DO NOTHING",
                (self.deployment, json.dumps({"deployment": self.deployment})),
            )
            row = tx.execute(
                "SELECT payload FROM r2s_gpu_control WHERE deployment_id=?" + tx.lock_suffix(), (self.deployment,)
            ).fetchone()
            control = load_control(json.loads(row[0]))
            yield tx, control, db_time(tx)
            control.version += 1
            tx.execute(
                "UPDATE r2s_gpu_control SET payload=? WHERE deployment_id=?",
                (json.dumps(control_payload(control)), self.deployment),
            )

    def read(self) -> Control:
        with self.locked() as (_, control, _):
            return control

    def history(self, tx: RuntimeTransaction, control: Control, now: float) -> None:
        tx.execute(
            "INSERT INTO r2s_gpu_history(intent_id,deployment_id,payload) VALUES (?,?,?) "
            "ON CONFLICT(intent_id) DO UPDATE SET payload=excluded.payload",
            (control.intent, control.deployment, json.dumps({**control_payload(control), "observed_at": now})),
        )


def claim_allowed(tx: RuntimeTransaction, kind: str | None = None, *, mark_busy: bool = False) -> bool:
    """Serialize managed claims against drain, in the *same* queue transaction."""
    import os

    if kind is not None and not supports(kind):
        return False
    deployment = os.environ.get("GPU_DEPLOYMENT_ID", "")
    token = os.environ.get("GPU_BOOT_TOKEN", "")
    if not token:
        # An enabled deployment must not have an unregistered legacy worker claiming jobs.
        return cpu_lane() or os.environ.get("GPU_MANAGED_CLAIMS_REQUIRED", "false").lower() != "true"
    suffix = " FOR UPDATE" if tx.postgres else ""
    row = tx.execute(
        f"SELECT payload FROM {table(tx, 'r2s_gpu_control')} WHERE deployment_id=?" + suffix, (deployment,)
    ).fetchone()
    if row is None:
        return False
    data = json.loads(row[0])
    allowed = data["boot_token"] == token and data["state"] in {"ready", "busy", "idle"} and not data["drain"]
    if allowed and mark_busy:
        key = os.environ.get("GPU_WORKER_KEY", "")
        if key not in data["workers"]:
            return False
        data["workers"][key].update(busy=True, heartbeat=db_time(tx))
        tx.execute(
            f"UPDATE {table(tx, 'r2s_gpu_control')} SET payload=? WHERE deployment_id=?", (json.dumps(data), deployment)
        )
    return allowed


def cpu_lane() -> bool:
    import os

    return os.environ.get("GPU_CPU_LANE", "false").lower() == "true"


def supports(kind: str) -> bool:
    import os

    if cpu_lane():
        if kind == "scene":
            from src.config import get_settings
            from src.services.orchestration.gpu.catalog import load_catalog

            path = get_settings().product_gpu_release_catalog
            profiles = load_catalog(path).compatible("scene") if path else []
            return bool(profiles) and not any(p.scene_boxes_require_gpu for p in profiles)
        return kind in {"registration", "import"}
    profile = os.environ.get("GPU_EXPECTED_PROFILE")
    return not profile or kind in json.loads(profile)["kinds"]
