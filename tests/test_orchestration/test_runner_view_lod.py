"""T-070: bước tạo bộ LOD chạy ngay sau khi job xong, trong cùng lượt (giữ lease nên máy GPU không bị tắt giữa chừng)."""

from types import SimpleNamespace

from src.services.orchestration.jobs import runner


class _Persistence:
    def __init__(self) -> None:
        self.database = object()

    def list_attempts(self, job_id):  # noqa: ANN001, ANN201
        return [SimpleNamespace(attempt=3)]


def _attempt(tmp_path):  # noqa: ANN001, ANN202
    sog = SimpleNamespace(artifact_uri="artifact://jobs/job-a/rec06/scene.sog", artifact_checksum="sha256:" + "a" * 64)
    registry = SimpleNamespace(
        persistence=_Persistence(),
        runtime_resolver=SimpleNamespace(artifact_root=tmp_path, remote=None, require=lambda ref: tmp_path / "s.sog"),
        viewable_sogs=lambda job_id: [sog],
    )
    return SimpleNamespace(
        registry=registry,
        job=SimpleNamespace(job_id="job-a"),
        settings=SimpleNamespace(product_worker_root=tmp_path / "worker"),
    )


def test_view_lod_step_records_start_and_finish(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    writes = []
    monkeypatch.setattr(
        runner, "record_marks", lambda db, job, kind, run, items: writes.append((kind, run, list(items)))
    )
    monkeypatch.setattr(runner.lod, "lod_cli", lambda: tmp_path / "cli.mjs")
    monkeypatch.setattr(runner.lod, "build_job_view_lods", lambda *args: 1)
    runner._build_view_lods(_attempt(tmp_path))
    kinds = [(item.kind, item.step_id, item.outcome) for _, _, items in writes for item in items]
    assert kinds == [("start", "ST-VIEW-LOD", None), ("finish", "ST-VIEW-LOD", "succeeded")]
    assert {run for _, run, _ in writes} == {"3"}


def test_view_lod_failure_never_fails_the_job(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    writes = []
    monkeypatch.setattr(runner, "record_marks", lambda db, job, kind, run, items: writes.append(list(items)))
    monkeypatch.setattr(runner.lod, "lod_cli", lambda: tmp_path / "cli.mjs")

    def broken(*args):  # noqa: ANN002, ANN202
        raise RuntimeError("gpu fell over")

    monkeypatch.setattr(runner.lod, "build_job_view_lods", broken)
    runner._build_view_lods(_attempt(tmp_path))
    assert writes[-1][0].outcome == "failed"


def test_no_gpu_worker_skips_the_step_silently(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    writes = []
    monkeypatch.setattr(runner, "record_marks", lambda *args: writes.append(args))
    monkeypatch.setattr(runner.lod, "lod_cli", lambda: None)
    runner._build_view_lods(_attempt(tmp_path))
    assert writes == []


def test_shutdown_during_the_step_closes_its_mark_and_still_stops(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """Review fix: a worker stopped mid-build must not leave "running" forever on a finished scene."""
    import pytest

    writes = []
    monkeypatch.setattr(runner, "record_marks", lambda db, job, kind, run, items: writes.append(list(items)))
    monkeypatch.setattr(runner.lod, "lod_cli", lambda: tmp_path / "cli.mjs")

    def interrupted(*args):  # noqa: ANN002, ANN202
        raise KeyboardInterrupt

    monkeypatch.setattr(runner.lod, "build_job_view_lods", interrupted)
    with pytest.raises(KeyboardInterrupt):
        runner._build_view_lods(_attempt(tmp_path))
    assert writes[-1][0].kind == "finish" and writes[-1][0].outcome == "cancelled"


def test_a_database_blip_on_the_start_mark_does_not_fail_the_finished_job(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    calls = []

    def flaky(db, job, kind, run, items):  # noqa: ANN001, ANN202
        calls.append(list(items))
        if len(calls) == 1:
            raise RuntimeError("db blip")

    monkeypatch.setattr(runner, "record_marks", flaky)
    monkeypatch.setattr(runner.lod, "lod_cli", lambda: tmp_path / "cli.mjs")
    monkeypatch.setattr(runner.lod, "build_job_view_lods", lambda *args: 1)
    runner._build_view_lods(_attempt(tmp_path))
    assert calls[-1][0].outcome == "succeeded"
