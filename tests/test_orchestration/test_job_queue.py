"""Hàng đợi: xoay vòng theo người yêu cầu, vị trí khớp thứ tự worker nhận, thời gian chờ chỉ từ số đo."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from src.models.contracts.manifests import JobManifest, JobStatus, StageId
from src.services.orchestration.auth.models import Actor
from src.services.orchestration.jobs.models import TransitionRequest
from src.services.orchestration.jobs.progress import job_progress
from src.services.orchestration.jobs.queue import (
    WaitingJob,
    fair_order,
    job_requester_actors,
    queue_position,
    waiting_jobs,
)
from src.services.orchestration.jobs.worker_cli import dispatch_next
from src.services.orchestration.projects.models import JobCreateInput
from src.services.orchestration.projects.registry import ProjectRegistry
from tests.test_orchestration.test_metric_confirmation_record import _confirmation
from tests.test_orchestration.test_prepared_queue import _attach_frames, _frame_stage, _registry

T0 = datetime(2026, 10, 2, 8, tzinfo=UTC)


def _waiting(job_id: str, minutes: int, owner: str | None, phase: str = "preview") -> WaitingJob:
    return WaitingJob(job_id=job_id, phase=phase, queued_at=T0 + timedelta(minutes=minutes), owner=owner)


def test_round_robin_between_requesters() -> None:
    """An gửi ba video trước, Bình gửi một video sau: video của Bình chạy ngay sau video đầu của An."""
    jobs = [_waiting("a1", 0, "an"), _waiting("a2", 1, "an"), _waiting("a3", 2, "an"), _waiting("b1", 3, "binh")]
    assert [job.job_id for job in fair_order(jobs)] == ["a1", "b1", "a2", "a3"]
    late = [*jobs, _waiting("c1", 9, "chi"), _waiting("b2", 10, "binh")]
    assert [job.job_id for job in fair_order(late)] == ["a1", "b1", "c1", "a2", "b2", "a3"]
    # Worker chạy tuần tự: a1 vừa chạy xong thì An là người mới được phục vụ → Bình (chưa từng) đi trước a2.
    served = T0 + timedelta(minutes=30)
    after = [job.model_copy(update={"owner_served_at": served}) for job in jobs[1:3]] + [jobs[3]]
    assert [job.job_id for job in fair_order(after)] == ["b1", "a2", "a3"]


def test_without_accounts_it_is_first_come_first_served() -> None:
    jobs = [_waiting("z", 0, None), _waiting("a", 5, None), _waiting("m", 2, None)]
    assert [job.job_id for job in fair_order(jobs)] == ["z", "m", "a"]  # theo thời điểm vào hàng, không theo id
    tie = [_waiting("b", 0, None), _waiting("a", 0, None)]
    assert [job.job_id for job in fair_order(tie)] == ["a", "b"]  # cùng lúc thì ổn định theo id
    assert fair_order([]) == []


def _job(registry: ProjectRegistry, suffix: str) -> JobManifest:
    job = registry.create_job(JobCreateInput(project_id="project-fixture-001"))
    return _attach_frames(registry, job, _frame_stage(job.job_id, suffix))


def _audit(registry: ProjectRegistry, user: str, job_id: str, at: datetime) -> None:
    payload = {
        "entry_id": uuid4().hex,
        "at": at.isoformat(),
        "user_id": user,
        "action": "gpu.run",
        "target": job_id,
        "details": {},
    }
    with registry.persistence.database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_audit_log(entry_id, at, user_id, action, payload) VALUES (?,?,?,?,?)",
            (payload["entry_id"], payload["at"], user, "gpu.run", json.dumps(payload)),
        )


def _usage(registry: ProjectRegistry, tool: str, seconds: float, attempt: str, outcome: str = "completed") -> None:
    record = {
        "job_id": "job-earlier",
        "attempt_id": attempt,
        "tool": tool,
        "outcome": outcome,
        "duration_seconds": seconds,
    }
    with registry.persistence.database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_resource_usage(usage_id,job_id,recorded_at,payload) VALUES (?,?,?,?)",
            (uuid4().hex, "job-earlier", T0.isoformat(), json.dumps(record)),
        )


def test_waiting_jobs_come_from_the_journal_with_their_requesters(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "runtime")
    queued = _job(registry, "a")
    running = registry.transition_job(_job(registry, "b").job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    waiting_user = registry.record_stage_progress(running, StageId.METRIC_CANONICALIZE)  # chờ NGƯỜI xác nhận
    confirmed = registry.transition_job(_job(registry, "c").job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    confirmed = registry.record_stage_progress(confirmed, StageId.METRIC_CANONICALIZE)
    confirmed = registry.record_metric_confirmation(confirmed, _confirmation(registry, confirmed.job_id))
    _audit(registry, "user-an", queued.job_id, T0)
    _audit(registry, "user-binh", queued.job_id, T0 + timedelta(minutes=1))  # Bình bấm thử lại sau cùng
    found = {item.job_id: item for item in waiting_jobs(registry)}
    assert set(found) == {queued.job_id, confirmed.job_id}  # job đã xong và job chờ người dùng không nằm trong hàng
    assert waiting_user.job_id not in found
    assert found[queued.job_id].phase == "preview" and found[queued.job_id].owner == "user-binh"
    assert found[confirmed.job_id].phase == "finalize" and found[confirmed.job_id].owner is None


def test_legacy_requester_keeps_unknown_historical_role(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "runtime")
    queued = _job(registry, "d")
    _audit(registry, "user-an", queued.job_id, T0)

    actors = job_requester_actors(
        registry.persistence.database,
        {"user-an": Actor(user_id="user-an", display_name="An")},
    )

    assert actors[queued.job_id].display_name == "An"
    assert actors[queued.job_id].role is None


def test_worker_takes_jobs_in_fair_order(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "runtime")
    first, second, third = _job(registry, "a"), _job(registry, "b"), _job(registry, "c")
    for job in (first, second):
        _audit(registry, "user-an", job.job_id, T0)
    _audit(registry, "user-binh", third.job_id, T0)
    expected = [item.job_id for item in fair_order(waiting_jobs(registry))]
    assert expected.index(third.job_id) == 1  # job của Bình chen giữa hai job của An
    position = queue_position(registry, third.job_id)
    assert position is not None and position.position == 2  # UI báo đúng thứ tự worker sẽ nhận
    taken: list[str] = []

    def run(job_id: str, uri: str, *, expected_checksum: str) -> JobManifest:
        taken.append(job_id)
        return registry.transition_job(job_id, TransitionRequest(target_status=JobStatus.RUNNING))

    while dispatch_next(registry, runner=run):
        pass
    assert taken == expected


def test_position_matches_dispatch_order_and_wait_uses_only_measured_durations(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "runtime")
    jobs = [_job(registry, suffix) for suffix in "abc"]
    order = [item.job_id for item in fair_order(waiting_jobs(registry))]
    now = datetime.now(UTC)
    first = queue_position(registry, order[0], now)
    last = queue_position(registry, order[2], now)
    assert first is not None and last is not None
    assert (first.position, first.waiting, first.running, first.workers) == (1, 3, 0, 1)
    assert first.estimated_wait_seconds == 0 and last.position == 3
    assert last.estimated_wait_seconds is None and last.estimate_samples == 0  # chưa có số đo: không đoán
    # Hai lượt preview đã đo: 100 + 500 = 600 s và 80 + 320 = 400 s; lượt lỗi không được tính.
    _usage(registry, "prepare", 100, "attempt-1")
    _usage(registry, "preview", 500, "attempt-1")
    _usage(registry, "prepare", 80, "attempt-2")
    _usage(registry, "preview", 320, "attempt-2")
    _usage(registry, "preview", 5, "attempt-3", outcome="failed")
    last = queue_position(registry, order[2], now)
    assert last is not None and last.estimated_wait_seconds == pytest.approx(2 * 500) and last.estimate_samples == 2
    # Một job đang chạy được 200 s (ước 500 s) → còn 300 s; hai worker thì chia đôi.
    reservation = {"reserved_at": (now - timedelta(seconds=200)).isoformat(), "phase": "preview"}
    with registry.persistence.database.transaction(write=True) as tx:
        tx.execute(
            "INSERT INTO r2s_resource_reservations(worker_id,payload) VALUES (?,?)", ("w1", json.dumps(reservation))
        )
        for worker in ("w1", "w2"):
            tx.execute(
                "INSERT INTO r2s_workers(worker_id,payload) VALUES (?,?)",
                (worker, json.dumps({"measured_at": now.isoformat()})),
            )
    last = queue_position(registry, order[2], now)
    assert last is not None and (last.running, last.workers) == (1, 2)
    assert last.estimated_wait_seconds == pytest.approx((300 + 2 * 500) / 2)
    assert queue_position(registry, "job-fixture-001", now) is None  # job đã xong không ở trong hàng
    assert jobs[0].job_id in order


def test_finalize_wait_needs_finalize_measurements(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "runtime")
    _usage(registry, "preview", 500, "attempt-1")
    confirmed = registry.transition_job(_job(registry, "a").job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    confirmed = registry.record_stage_progress(confirmed, StageId.METRIC_CANONICALIZE)
    confirmed = registry.record_metric_confirmation(confirmed, _confirmation(registry, confirmed.job_id))
    behind = _job(registry, "b")
    order = [item.job_id for item in fair_order(waiting_jobs(registry))]
    target = queue_position(registry, order[-1])
    assert target is not None and target.position == 2
    assert target.estimated_wait_seconds is None  # job phía trước là bước hoàn tất, chưa có số đo cho pha đó
    _usage(registry, "finalize", 90, "finalize-1")
    _usage(registry, "scene_extract", 1200, "finalize-1")
    target = queue_position(registry, order[-1])
    ahead_phase = next(item.phase for item in waiting_jobs(registry) if item.job_id == order[0])
    assert target is not None
    assert target.estimated_wait_seconds == pytest.approx(1290 if ahead_phase == "finalize" else 500)
    assert behind.job_id in order and confirmed.job_id in order


def test_progress_reports_queue_only_while_waiting_for_a_worker(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "runtime")
    job = _job(registry, "a")
    position = queue_position(registry, job.job_id)
    progress = job_progress(job, registry.list_job_attempts(job.job_id), False, None, position)
    assert progress.queue is not None and progress.queue.position == 1
    running = registry.transition_job(job.job_id, TransitionRequest(target_status=JobStatus.RUNNING))
    progress = job_progress(running, registry.list_job_attempts(job.job_id), False, None, position)
    assert progress.queue is None  # đang chạy: vị trí cũ không còn nghĩa
