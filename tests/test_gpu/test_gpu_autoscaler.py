"""Tự bật/tắt GPU (scripts/cloud/gpu_autoscaler.py): quyết định, vòng lặp, và lời gọi vast.ai qua transport giả.

Fixture proof: không gọi vast.ai thật; chỉ chứng minh logic và dạng request theo tài liệu.
"""

from datetime import UTC, datetime, timedelta

import pytest

from scripts.cloud.gpu_autoscaler import (
    WORKER_LABEL,
    Autoscaler,
    AutoscalerError,
    RentSpec,
    VastInstance,
    VastRental,
    Workload,
    decide,
    provider_from_environment,
)

LIMIT = timedelta(minutes=10)


class FakeProvider:
    def __init__(self, state: str = "absent") -> None:
        self.current, self.calls = state, []

    def state(self) -> str:
        return self.current

    def start(self) -> None:
        self.calls.append("start")
        self.current = "starting"

    def stop(self) -> None:
        self.calls.append("stop")
        self.current = "absent"


class FakeVast:
    """Ghi lại request; trả phản hồi theo (method, tiền tố path)."""

    def __init__(self, responses: dict[tuple[str, str], dict]) -> None:
        self.responses, self.requests = responses, []

    def __call__(self, method: str, path: str, body: dict | None) -> dict:
        self.requests.append((method, path, body))
        for (expected_method, prefix), response in self.responses.items():
            if method == expected_method and path.startswith(prefix):
                return response
        return {"success": True}


@pytest.mark.parametrize(
    ("workload", "state", "idle", "expected"),
    [
        (Workload(1, 0), "absent", timedelta(0), "start"),
        (Workload(1, 0), "stopped", timedelta(0), "start"),
        (Workload(1, 0), "starting", timedelta(0), "none"),  # đang bật rồi, không thuê thêm
        (Workload(2, 1), "running", timedelta(0), "none"),
        (Workload(0, 1), "running", timedelta(hours=1), "none"),  # đang chạy dở thì không tắt
        (Workload(0, 0), "running", timedelta(minutes=9), "none"),
        (Workload(0, 0), "running", timedelta(minutes=10), "stop"),
        (Workload(0, 0), "starting", timedelta(minutes=10), "stop"),  # bật lên rồi việc bị huỷ
        (Workload(0, 0), "absent", timedelta(hours=5), "none"),
    ],
)
def test_decide(workload: Workload, state: str, idle: timedelta, expected: str) -> None:
    assert decide(workload, state, idle, LIMIT) == expected  # type: ignore[arg-type]


def test_loop_starts_on_work_and_stops_only_after_idle_limit() -> None:
    now = [datetime(2026, 10, 1, tzinfo=UTC)]
    work = [Workload(1, 0)]
    provider = FakeProvider()
    scaler = Autoscaler(provider, lambda: work[0], LIMIT, clock=lambda: now[0])

    assert scaler.tick() == "start"
    provider.current, work[0] = "running", Workload(0, 1)
    now[0] += timedelta(minutes=30)
    assert scaler.tick() == "none"  # việc đang chạy giữ GPU bật
    work[0] = Workload(0, 0)
    now[0] += timedelta(minutes=9)
    assert scaler.tick() == "none"
    now[0] += timedelta(minutes=1)
    assert scaler.tick() == "stop"
    assert provider.calls == ["start", "stop"]


def test_restart_does_not_stop_gpu_immediately_and_dry_run_calls_nothing() -> None:
    now = [datetime(2026, 10, 1, tzinfo=UTC)]
    provider = FakeProvider("running")
    scaler = Autoscaler(provider, lambda: Workload(0, 0), LIMIT, clock=lambda: now[0], dry_run=True)

    assert scaler.tick() == "none"  # vừa khởi động: chưa biết rảnh bao lâu
    now[0] += timedelta(minutes=11)
    assert scaler.tick() == "stop"
    assert provider.calls == []  # dry-run


def test_vast_instance_maps_state_and_toggles() -> None:
    vast = FakeVast(
        {("GET", "/instances/77/"): {"instances": {"actual_status": "exited", "intended_status": "stopped"}}}
    )
    instance = VastInstance(vast, "77")
    assert instance.state() == "stopped"
    instance.start()
    instance.stop()
    assert vast.requests[1:] == [
        ("PUT", "/instances/77/", {"state": "running"}),
        ("PUT", "/instances/77/", {"state": "stopped"}),
    ]
    vast.responses[("GET", "/instances/77/")] = {
        "instances": {"actual_status": "loading", "intended_status": "running"}
    }
    assert instance.state() == "starting"
    with pytest.raises(AutoscalerError, match="VAST_INSTANCE_ID"):
        VastInstance(FakeVast({("GET", "/instances/"): {}}), "9").state()


def _spec(max_dph: float = 0.5) -> RentSpec:
    return RentSpec(
        "user/real2sim-gpu:v2", 16, max_dph, 60, 0.98, {"DATABASE_URL": "postgresql://x", "ARTIFACT_S3_BUCKET": "b"}
    )


def test_vast_rental_rents_cheapest_offer_within_cap_with_worker_image() -> None:
    offers = [
        {"id": 1, "dph_total": 0.45, "gpu_name": "RTX 4090"},
        {"id": 2, "dph_total": 0.31, "gpu_name": "RTX 3090"},
    ]
    vast = FakeVast(
        {
            ("GET", "/instances/"): {"instances": [{"id": 5, "label": "việc khác", "actual_status": "running"}]},
            ("POST", "/bundles/"): {"offers": [*offers, {"id": 3, "dph_total": 0.9}]},
            ("PUT", "/asks/"): {"success": True, "new_contract": 99},
        }
    )
    rental = VastRental(vast, _spec())

    assert rental.state() == "absent"  # instance của việc khác không tính
    rental.start()

    method, path, query = vast.requests[1]
    assert (method, path) == ("POST", "/bundles/")
    assert (
        query["gpu_ram"] == {"gte": 16384} and query["dph_total"] == {"lte": 0.5} and query["rentable"] == {"eq": True}
    )
    method, path, body = vast.requests[2]
    assert (method, path) == ("PUT", "/asks/2/")  # rẻ nhất
    assert body["image"] == "user/real2sim-gpu:v2" and body["label"] == WORKER_LABEL
    assert (body["runtype"], body["args"], body["disk"]) == ("args", ["worker"], 60)
    assert body["env"] == {"DATABASE_URL": "postgresql://x", "ARTIFACT_S3_BUCKET": "b"}


def test_vast_rental_refuses_when_nothing_fits_budget_and_destroys_only_own_instances() -> None:
    vast = FakeVast({("POST", "/bundles/"): {"offers": [{"id": 3, "dph_total": 0.9}]}})
    with pytest.raises(AutoscalerError, match="giá trần"):
        VastRental(vast, _spec()).start()
    assert not any(method == "PUT" for method, _, _ in vast.requests)

    mine = {"id": 8, "label": WORKER_LABEL, "actual_status": "running"}
    vast = FakeVast({("GET", "/instances/"): {"instances": [mine, {"id": 5, "label": "việc khác"}]}})
    rental = VastRental(vast, _spec())
    assert rental.state() == "running"
    rental.stop()
    assert [(m, p) for m, p, _ in vast.requests if m == "DELETE"] == [("DELETE", "/instances/8/")]


def test_provider_configuration_errors_name_the_missing_variable() -> None:
    with pytest.raises(AutoscalerError, match="VAST_API_KEY"):
        provider_from_environment({})
    with pytest.raises(AutoscalerError, match="VAST_INSTANCE_ID"):
        provider_from_environment({"VAST_API_KEY": "k"})
    with pytest.raises(AutoscalerError, match="VAST_IMAGE"):
        provider_from_environment({"VAST_API_KEY": "k", "VAST_MODE": "rent"})
    with pytest.raises(AutoscalerError, match="DATABASE_URL, ARTIFACT_S3_BUCKET"):
        provider_from_environment({"VAST_API_KEY": "k", "VAST_MODE": "rent", "VAST_IMAGE": "i"})
    rental = provider_from_environment(
        {
            "VAST_API_KEY": "k",
            "VAST_MODE": "rent",
            "VAST_IMAGE": "i",
            "DATABASE_URL": "d",
            "ARTIFACT_S3_BUCKET": "b",
            "HOME": "/x",
        }
    )
    assert isinstance(rental, VastRental) and rental.spec.environment == {
        "DATABASE_URL": "d",
        "ARTIFACT_S3_BUCKET": "b",
    }
