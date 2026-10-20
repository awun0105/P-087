"""One-Pod reconciler. Provider calls never run inside a database transaction."""

import json
import math
import secrets
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

from dotenv import dotenv_values

from src.services.orchestration.gpu.catalog import ReleaseCatalog, ReleaseProfile
from src.services.orchestration.gpu.config import GpuSettings
from src.services.orchestration.gpu.provider import Provider, ProviderError
from src.services.orchestration.gpu.state import Control, StateStore
from src.services.orchestration.gpu.workload import Workload

WORKER_KEYS = frozenset(
    {
        "DATABASE_URL",
        "APP_ENV",
        "AUTH_REQUIRED",
        "AUTH_COOKIE_SECURE",
        "ARTIFACT_S3_BUCKET",
        "ARTIFACT_S3_ENDPOINT",
        "ARTIFACT_S3_REGION",
        "ARTIFACT_S3_ACCESS_KEY_ID",
        "ARTIFACT_S3_SECRET_ACCESS_KEY",
        "ARTIFACT_S3_PREFIX",
        "PRODUCT_DEMO_OBJECT_PREFIX",
        "PRODUCT_DEMO_SESSION_SECONDS",
        "PRODUCT_DEMO_IDLE_SECONDS",
        "PRODUCT_PRIVACY_MODE",
        "PRODUCT_ANONYMIZE_INPUT",
        "PRODUCT_EGOBLUR_WEIGHTS",
        "PRODUCT_OBJECTIFY",
        "PRODUCT_COLMAP_USE_GPU",
        "PRODUCT_PROCESSING_CONFIG",
        "PRODUCT_GEOMETRY_CONFIG",
        "PRODUCT_SEED",
        "PRODUCT_ISAAC_VALIDATION_CONFIG",
        "PRODUCT_ISAAC_VALIDATION_PROFILE",
        "PRODUCT_ISAAC_VALIDATION_LAUNCHER",
        "PRODUCT_ISAAC_VALIDATION_RESOURCES",
        "OMNI_KIT_ACCEPT_EULA",
        "PRODUCT_INPUT_RUNTIME_REGISTRY",
    }
)


#: Newest version RunPod's allowedCudaVersions enum accepts. Hosts with newer drivers report newer CUDA versions
#: that the filter cannot name, so listing this version means "this or newer" and the filter is omitted.
_RUNPOD_NEWEST_CUDA_FILTER = "13.0"


def _cuda_filter(versions: tuple[str, ...]) -> dict:
    """allowedCudaVersions for the create payload; omitted when the profile accepts the newest filterable CUDA."""
    if _RUNPOD_NEWEST_CUDA_FILTER in versions:
        return {}
    return {"allowedCudaVersions": list(versions)}


class Controller:
    def __init__(
        self,
        store: StateStore,
        policy: GpuSettings,
        catalog: ReleaseCatalog,
        provider: Provider,
        workload: Callable[[], Workload],
    ) -> None:
        self.store, self.policy, self.catalog, self.provider, self.workload = store, policy, catalog, provider, workload
        self.owner = uuid4().hex

    def _save(self, snapshot: Control) -> bool:
        with self.store.locked() as (tx, current, now):
            if current.owner != self.owner or current.leader_until <= now or current.intent != snapshot.intent:
                return False
            if snapshot.state != current.state:
                snapshot.phase_seconds = dict(current.phase_seconds)
                if current.phase_since:
                    snapshot.phase_seconds[current.state] = snapshot.phase_seconds.get(current.state, 0) + max(
                        0, now - current.phase_since
                    )
                snapshot.phase_since = now
            snapshot.workers, snapshot.drain = current.workers, current.drain
            current.__dict__.update(snapshot.__dict__)
            if current.intent:
                self.store.history(tx, current, now)
            return True

    @staticmethod
    def owned(pod: dict, c: Control, profile: ReleaseProfile) -> bool:
        env = pod.get("env") or {}
        return (
            isinstance(env, dict)
            and pod.get("name") == f"r2s-{c.deployment}-{c.intent}"
            # RunPod returns "image": null alongside "imageName"; a present-but-null key must not hide imageName.
            and (pod.get("image") or pod.get("imageName")) == profile.image
            and env.get("GPU_BOOT_TOKEN") == c.boot_token
            and env.get("GPU_DEPLOYMENT_ID") == c.deployment
            and env.get("GPU_INTENT_ID") == c.intent
        )

    def _payload(self, c: Control, profile: ReleaseProfile, gpu_type: str) -> dict:
        values = dotenv_values(self.policy.worker_env_file) if self.policy.worker_env_file else {}
        env = {key: str(value) for key, value in values.items() if key in WORKER_KEYS and value is not None}
        if not env.get("DATABASE_URL", "").startswith(("postgresql://", "postgres://")) or not env.get(
            "ARTIFACT_S3_BUCKET"
        ):
            raise ValueError("Worker env requires PostgreSQL and object storage")
        env.update(
            {
                "GPU_DEPLOYMENT_ID": c.deployment,
                "GPU_INTENT_ID": c.intent,
                "GPU_BOOT_TOKEN": c.boot_token,
                "GPU_EXPECTED_PROFILE": profile.model_dump_json(),
                "GPU_MANAGED_CLAIMS_REQUIRED": "true",
                "STUDIO_WORKERS": "1",
                "PRODUCT_DEMO_REQUIRED": "false",
                "PRODUCT_DEMO_ARCHIVE_KEY": "",
            }
        )
        result = {
            "name": f"r2s-{c.deployment}-{c.intent}",
            "imageName": profile.image,
            "computeType": "GPU",
            "cloudType": self.policy.cloud_type,
            "gpuCount": 1,
            "gpuTypeIds": [gpu_type],
            **_cuda_filter(profile.cuda_versions),
            "gpuTypePriority": "custom",
            "interruptible": False,
            "containerDiskInGb": max(profile.scratch_gb, self.policy.container_disk_gb),
            "volumeInGb": 0,
            # RunPod's PodCreateInput.minRAMPerGPU is an int32; a float such as 32.0 is rejected with HTTP 400.
            "minRAMPerGPU": math.ceil(profile.min_ram_gb),
            "minVCPUPerGPU": profile.min_cpus,
            "dockerStartCmd": ["worker"],
            "env": env,
            "ports": [],
            "supportPublicIp": False,
        }
        if self.policy.registry_auth_id:
            result["containerRegistryAuthId"] = self.policy.registry_auth_id
        return result

    def _abandon_create(self, c: Control, error: ProviderError) -> str:
        """Retire a create the provider definitely refused, keeping its history and the attempt count."""
        with self.store.locked() as (tx, current, stamp):
            if current.owner != self.owner or current.intent != c.intent:
                return "follower"
            retired = replace(
                current, state="terminated", error=error.category, phase_seconds=dict(current.phase_seconds)
            )
            self.store.history(tx, retired, stamp)
            current.state, current.intent, current.pod, current.boot_token = "absent", "", "", ""
            current.profile_payload, current.workers, current.idle_since = {}, {}, None
            current.phase_since, current.estimated_usd = stamp, 0
            current.error, current.retry_at = error.category, stamp + error.retry_after
            if current.attempts >= self.policy.max_provision_attempts:
                current.drain = True  # Same circuit breaker as an empty inventory: operator resumes.
        return "create_refused"

    def forget_unknown(self) -> str:
        """Operator recovery for an unresolved create: retire it only if the provider has no Pod with its name.

        The name `r2s-<deployment>-<intent>` is unique per intent, so an empty match proves nothing was allocated
        under this intent. Anything else (a recorded Pod id, a matching Pod) is left for normal reconciliation.
        """
        snapshot = self.store.read()
        if snapshot.state not in {"unknown", "provisioning"} or not snapshot.intent or snapshot.pod:
            return "nothing_to_forget"
        name = f"r2s-{snapshot.deployment}-{snapshot.intent}"
        if any(pod.get("name") == name for pod in self.provider.list()):
            return "pod_exists"
        with self.store.locked() as (tx, current, stamp):
            if current.intent != snapshot.intent or current.pod or current.state not in {"unknown", "provisioning"}:
                return "changed"
            retired = replace(current, state="terminated", phase_seconds=dict(current.phase_seconds))
            self.store.history(tx, retired, stamp)
            current.state, current.intent, current.boot_token = "absent", "", ""
            current.profile_payload, current.workers, current.idle_since = {}, {}, None
            current.phase_since, current.estimated_usd, current.error = stamp, 0, "operator_forgot_unallocated_intent"
        return "forgotten"

    def tick(self) -> str:
        with self.store.locked() as (_, current, now):
            if current.owner != self.owner and current.leader_until > now:
                return "follower"
            current.owner, current.leader_until = self.owner, now + 120
            c = replace(current, workers=dict(current.workers))
        try:
            return self._tick(c, now)
        except ProviderError as error:
            c.error = error.category
            c.retry_at = now + error.retry_after
            if c.state == "provisioning":
                c.state = "unknown"  # Never retry a possibly accepted POST.
            self._save(c)
            return "provider_error"
        except (ValueError, OSError, RuntimeError) as error:
            c.error = type(error).__name__
            self._save(c)
            return "blocked"

    def _tick(self, c: Control, now: float) -> str:
        work = self.workload()  # Any failure prevents both provisioning and idle termination.
        if not work.complete:
            c.error = "incomplete_workload_scan"
            c.idle_since = None
            self._save(c)
            return "scan_unknown"
        if c.intent:
            c.estimated_usd = max(c.estimated_usd, (now - c.created_at) * c.rate / 3600)
        if now < c.retry_at:
            self._save(c)
            return "backoff"
        pods = self.provider.list()  # API contract returns a complete array, not a paginated envelope.
        if c.state == "absent":
            with self.store.database.transaction() as tx:
                history = [
                    json.loads(row[0])
                    for row in tx.execute(
                        "SELECT payload FROM r2s_gpu_history WHERE deployment_id=?", (c.deployment,)
                    ).fetchall()
                ]
            historic = [(pod, h) for pod in pods for h in history if h.get("pod") == pod.get("id")]
            if historic:
                # Reconcile even with an empty queue or disabled provisioning. An eventual-consistency
                # false absence must not strand an owned stopped/running Pod forever.
                pod, record = historic[0]
                old = Control(**{key: value for key, value in record.items() if key in Control.__dataclass_fields__})
                pinned = ReleaseProfile.model_validate(old.profile_payload) if old.profile_payload else None
                if len(historic) == 1 and pinned is not None and self.owned(pod, old, pinned):
                    with self.store.locked() as (_, current, _):
                        if current.owner != self.owner or current.state != "absent":
                            return "follower"
                        current.intent, current.pod = old.intent, old.pod
                        current.profile, current.profile_payload = old.profile, old.profile_payload
                        current.boot_token, current.rate, current.created_at = old.boot_token, old.rate, old.created_at
                        current.state, current.error = "draining", "historic_pod_adopted"
                        current.workers = {}
                    return "adopted_historic"
                c.error = "historic_pod_ownership_requires_review"
                self._save(c)
                return "blocked"
            if not self.policy.autoprov_enabled or c.drain or not work.pending:
                return "no_work"
            if c.attempts >= self.policy.max_provision_attempts:
                c.error = "provisioning_attempts_exhausted"
                self._save(c)
                return "blocked"
            allowed = work.pending[0].profiles
            profile = next(p for p in self.catalog.profiles if p.name in allowed)
            offers = self.provider.quotes(profile.gpu_types, self.policy.cloud_type == "SECURE")
            offers = [
                q
                for q in offers
                if q.vram_gb >= profile.min_vram_gb
                and q.hourly + profile.storage_hourly_usd <= (self.policy.max_hourly_usd or 0)
            ]
            spent = sum(h.get("estimated_usd", 0) for h in history)
            if not offers:
                c.attempts += 1
                c.error = "no_compatible_inventory_within_price"
                c.retry_at = now + min(300, 15 * 2**c.attempts)
                if c.attempts >= self.policy.max_provision_attempts:
                    c.drain = True
                # drain is an operator-owned field: persist explicit circuit breaker separately.
                with self.store.locked() as (_, current, _):
                    if current.owner == self.owner:
                        current.drain |= c.drain
                self._save(c)
                return "inventory_blocked"
            rate = offers[0].hourly + profile.storage_hourly_usd
            reserve = rate * (self.policy.startup_timeout_seconds + self.policy.idle_seconds) / 3600
            if spent + reserve > (self.policy.project_budget_usd or 0):
                c.error = "budget_exhausted"
                self._save(c)
                return "budget_blocked"
            if self.policy.autoprov_dry_run:
                return "would_create"
            intent, token = uuid4().hex, secrets.token_hex(32)
            prospective = replace(c, intent=intent, boot_token=token, profile=profile.name)
            payload = self._payload(prospective, profile, offers[0].gpu_type)
            # Persist an irrevocable create intent before crossing the provider boundary.
            with self.store.locked() as (tx, current, stamp):
                if current.owner != self.owner or current.state != "absent" or current.drain:
                    return "follower"
                current.intent, current.boot_token, current.profile = intent, token, profile.name
                current.profile_payload = profile.model_dump(mode="json")
                current.state, current.created_at, current.rate = "provisioning", stamp, rate
                current.phase_since, current.phase_seconds = stamp, {}
                current.attempts += 1
                current.idle_since, current.error, current.estimated_usd = None, "", 0
                c = replace(current, workers={})
                self.store.history(tx, c, stamp)
            try:
                pod = self.provider.create(payload)
            except ProviderError as error:
                if not error.ambiguous:
                    # Definitely not allocated (rejected request or no capacity): retire the intent and retry later.
                    return self._abandon_create(c, error)
                c.state, c.error = "unknown", error.category
                c.retry_at = now + error.retry_after
                self._save(c)
                return "provider_error"
            c.pod, c.state = str(pod["id"]), "starting"
            self._save(c)
            return "created"
        profile = (
            ReleaseProfile.model_validate(c.profile_payload)
            if c.profile_payload
            else next(p for p in self.catalog.profiles if p.name == c.profile)
        )
        matches = [p for p in pods if self.owned(p, c, profile)]
        if len(matches) > 1:
            c.error = "duplicate_owned_pods_requires_reconciliation"
            self._save(c)
            return "blocked"
        pod = matches[0] if matches else None
        if pod is None and c.pod:
            direct = self.provider.get(c.pod)
            if direct is not None:
                if not self.owned(direct, c, profile):
                    c.error = "ownership_mismatch"
                    self._save(c)
                    return "blocked"
                pod = direct
        if pod is None:
            if c.state in {"provisioning", "unknown"} or not c.pod:
                c.state, c.error = "unknown", "create_response_unknown"
                self._save(c)
                return "reconcile_unknown"
            self._save(c)
            with self.store.locked() as (tx, current, stamp):
                if current.owner != self.owner or current.intent != c.intent:
                    return "follower"
                retired = replace(current, state="terminated", phase_seconds=dict(current.phase_seconds))
                if current.phase_since:
                    retired.phase_seconds[current.state] = retired.phase_seconds.get(current.state, 0) + max(
                        0, stamp - current.phase_since
                    )
                self.store.history(tx, retired, stamp)
                current.state, current.intent, current.pod = "absent", "", ""
                current.phase_since = stamp
                current.boot_token, current.workers, current.idle_since = "", {}, None
                current.estimated_usd = 0
            return "terminated_confirmed"
        c.pod = str(pod["id"])
        if c.state in {"unknown", "provisioning"}:
            c.state = "starting"
        live = [w for w in c.workers.values() if now - w["heartbeat"] < 90]
        active = work.active > 0 or any(w.get("busy") for w in live)
        ready = any(w.get("ready") for w in live)
        try:
            actual = float(pod["costPerHr"]) + profile.storage_hourly_usd
        except (KeyError, ValueError, TypeError):
            actual = float("inf")
        try:
            allocation_ok = (
                (pod.get("machine") or {}).get("gpuTypeId") in profile.gpu_types
                # RunPod REST returns a top-level gpuCount with "gpu": null; older shapes nest it under gpu.count.
                and int(pod.get("gpuCount") or (pod.get("gpu") or {}).get("count") or 0) == 1
                and float(pod.get("memoryInGb") or 0) >= profile.min_ram_gb
                and int(pod.get("vcpuCount") or 0) >= profile.min_cpus
            )
        except (ValueError, TypeError, AttributeError):
            allocation_ok = False
        if actual < float("inf"):
            c.rate = max(c.rate, actual)
        with self.store.database.transaction() as tx:
            past_cost = sum(
                json.loads(row[0]).get("estimated_usd", 0)
                for row in tx.execute(
                    "SELECT payload FROM r2s_gpu_history WHERE deployment_id=? AND intent_id<>?",
                    (c.deployment, c.intent),
                ).fetchall()
            )
        retire = (
            now - c.created_at >= self.policy.max_lifetime_seconds
            or past_cost + c.estimated_usd >= (self.policy.project_budget_usd or float("inf"))
            or not self.policy.autoprov_enabled
            or c.drain
        )
        if c.state == "terminating":
            if not self.policy.autoprov_dry_run:
                self.provider.terminate(c.pod)
            self._save(c)
            return "terminating"
        if c.state == "starting":
            if ready and allocation_ok and actual <= (self.policy.max_hourly_usd or 0) and not retire:
                c.state, c.error, c.attempts = "ready", "", 0
            else:
                expired = now - c.created_at >= self.policy.startup_timeout_seconds
                overprice = actual < float("inf") and actual > (self.policy.max_hourly_usd or 0)
                if expired or overprice or retire or (ready and not allocation_ok):
                    c.state, c.error = "draining", "startup_or_allocation_failed"
                self._save(c)
                return c.state
        if active:
            c.idle_since = None
            if retire:
                c.state = "draining"
            elif c.state != "draining":
                c.state = "busy"
            self._save(c)
            return "busy"
        if c.state not in {"starting", "draining"} and (not ready or pod.get("desiredStatus") != "RUNNING"):
            c.state, c.error = "draining", "worker_unavailable"
            self._save(c)
            return "draining"
        current_release = any(
            p.name == c.profile and p.image == profile.image and p.execution == profile.execution
            for p in self.catalog.profiles
        )
        relevant = current_release and any(c.profile in item.profiles for item in work.pending)
        if c.state == "draining":
            if relevant and not retire and not c.error:
                c.state, c.idle_since = "ready", None
                self._save(c)
                return "drain_cancelled"
            # Gate closed in previous committed tick; claims lock the same control row.
            c.state = "terminating"
            self._save(c)
            return "drained"
        if relevant and not retire:
            c.state, c.idle_since = "ready", None
        else:
            c.idle_since = now if c.idle_since is None else c.idle_since
            c.state = "draining" if retire or now - c.idle_since >= self.policy.idle_seconds else "idle"
        self._save(c)
        return c.state
