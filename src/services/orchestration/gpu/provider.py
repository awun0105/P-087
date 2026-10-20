"""RunPod REST lifecycle adapter and read-only GraphQL inventory quotes."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote


class ProviderError(RuntimeError):
    def __init__(self, category: str, *, ambiguous: bool = False, retry_after: float = 30) -> None:
        super().__init__(category)  # Never include response bodies, URLs, env or credentials.
        self.category, self.ambiguous, self.retry_after = category, ambiguous, retry_after


Transport = Callable[[str, str, dict | None], object]
#: RunPod REST body when no machine matches the request; the create definitely did not allocate.
_NO_CAPACITY = b"no instances currently available"


def transport(api_key: str) -> Transport:
    def call(method: str, path: str, body: dict | None) -> object:
        url = "https://api.runpod.io/graphql" if path == "graphql" else "https://rest.runpod.io/v1" + path
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
                "User-Agent": "Real2Sim-deployment-preflight/1.0",
            },
            method=method,
        )
        creating = method == "POST" and path == "/pods"
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            if error.code == 404 and method in {"GET", "DELETE"}:
                return None
            category = "auth" if error.code in {401, 403} else "rate_limit" if error.code == 429 else "provider_http"
            try:
                delay = min(300.0, max(1.0, float(error.headers.get("Retry-After", "30"))))
            except ValueError:
                delay = 30
            # A create is only ambiguous when the provider might have accepted it. A schema rejection (400/422) and
            # "no instances currently available" are definite refusals; auth, rate limits and other errors stay
            # ambiguous as before. The body is only matched, never logged or put in the error.
            definite = error.code in {400, 422}
            if creating and not definite:
                try:
                    definite = _NO_CAPACITY in error.read(4096).lower()
                except OSError:
                    definite = False
                if definite:
                    category, delay = "inventory_unavailable", max(delay, 60)
            raise ProviderError(category, ambiguous=creating and not definite, retry_after=delay) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise ProviderError("transport", ambiguous=creating) from None

    return call


@dataclass(frozen=True)
class Quote:
    gpu_type: str
    hourly: float
    vram_gb: float


class Provider(Protocol):
    def list(self) -> list[dict]: ...
    def get(self, pod_id: str) -> dict | None: ...
    def create(self, payload: dict) -> dict: ...
    def terminate(self, pod_id: str) -> None: ...
    def quotes(self, gpu_types: tuple[str, ...], secure: bool) -> list[Quote]: ...


class RunPod:
    def __init__(self, call: Transport) -> None:
        self.call = call

    def list(self) -> list[dict]:
        result = self.call("GET", "/pods?includeMachine=true&includeNetworkVolume=true", None)
        if not isinstance(result, list) or any(not isinstance(p, dict) or not p.get("id") for p in result):
            raise ProviderError("invalid_list")
        return result

    def get(self, pod_id: str) -> dict | None:
        result = self.call("GET", "/pods/" + quote(pod_id, safe="") + "?includeMachine=true", None)
        if result is not None and (not isinstance(result, dict) or result.get("id") != pod_id):
            raise ProviderError("invalid_pod")
        return result

    def create(self, payload: dict) -> dict:
        result = self.call("POST", "/pods", payload)
        if not isinstance(result, dict) or not result.get("id"):
            raise ProviderError("invalid_create", ambiguous=True)
        return result

    def start(self, pod_id: str) -> None:
        self.call("POST", "/pods/" + quote(pod_id, safe="") + "/start", {})

    def stop(self, pod_id: str) -> None:
        self.call("POST", "/pods/" + quote(pod_id, safe="") + "/stop", {})

    def terminate(self, pod_id: str) -> None:
        self.call("DELETE", "/pods/" + quote(pod_id, safe=""), None)

    def quotes(self, gpu_types: tuple[str, ...], secure: bool) -> list[Quote]:
        # No API key in URL. Queries only; all lifecycle mutations use REST v1.
        query = (
            "query { gpuTypes { id memoryInGb lowestPrice(input: {gpuCount:1,secureCloud:"
            + str(secure).lower()
            + "}) { uninterruptablePrice stockStatus availableGpuCounts } } }"
        )
        result = self.call("POST", "graphql", {"query": query})
        if not isinstance(result, dict) or result.get("errors") or not isinstance(result.get("data"), dict):
            raise ProviderError("invalid_quote")
        offers = []
        for gpu in result["data"].get("gpuTypes", []):
            price = gpu.get("lowestPrice") or {}
            counts = price.get("availableGpuCounts")
            if gpu.get("id") not in gpu_types or (counts is not None and 1 not in counts):
                continue
            if (price.get("stockStatus") or "").lower() in {"none", "unavailable"}:
                continue
            try:
                rate, vram = float(price["uninterruptablePrice"]), float(gpu["memoryInGb"])
            except (KeyError, ValueError, TypeError):
                continue
            if 0 < rate < float("inf") and 0 < vram < float("inf"):
                offers.append(Quote(gpu["id"], rate, vram))
        return sorted(offers, key=lambda item: item.hourly)
