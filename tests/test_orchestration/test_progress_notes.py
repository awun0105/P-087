"""Dòng kết quả không suy thành công hay nguồn dữ liệu từ preset."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.manifests import JobManifest, JobStatus, StageArtifact, StageId
from src.services.orchestration.jobs import stage_results
from src.services.orchestration.jobs.progress import job_progress


def job() -> JobManifest:
    return JobManifest.model_validate_json(Path("fixtures/mock_job/job_manifest.json").read_bytes())


@pytest.mark.parametrize(
    "source,expected",
    [
        ("user_measured", "Bạn đo tay"),
        ("ai_estimated", "Tỉ lệ máy đề xuất từ ảnh, bạn đã chấp nhận"),
        ("lidar_trajectory", "Tỉ lệ máy đề xuất từ LiDAR, bạn đã chấp nhận"),
        ("lidar_demo", "Tỉ lệ đo từ LiDAR, bạn đã chấp nhận"),
    ],
)
def test_progress_metric_note_uses_accepted_source(monkeypatch: pytest.MonkeyPatch, source: str, expected: str) -> None:
    monkeypatch.setattr(stage_results, "recorded_results", lambda *_: {"metric": {"source": source}})
    notes = stage_results.stage_notes(None, job())
    assert notes[StageId.METRIC_CANONICALIZE] == expected
    progress = job_progress(job(), [], True, notes=notes)
    assert next(s for s in progress.stages if s.stage_id == StageId.METRIC_CANONICALIZE).note == expected


@pytest.mark.parametrize("source", ["ảnh", "LiDAR"])
def test_progress_collision_and_candidate_notes(monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    monkeypatch.setattr(
        stage_results, "recorded_results", lambda *_: {"collision_source": source, "candidate_count": 0}
    )
    notes = stage_results.stage_notes(None, job())
    assert notes == {StageId.RGB_GEOMETRY: f"Lưới từ {source}", StageId.OBJECT_EXTRACT: "0 vật ứng viên"}


def test_progress_missing_evidence_has_no_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stage_results, "recorded_results", lambda *_: {})
    assert stage_results.stage_notes(None, job()) == {}
    assert all(stage.note is None for stage in job_progress(job(), [], False).stages)
    assert stage_results.geometry_surface_note([SimpleNamespace(provenance={})]) is None
    assert (
        stage_results.geometry_surface_note(
            [
                SimpleNamespace(provenance={"surface_selection": {"chosen": chosen}})
                for chosen in ["objectgs", "gaussian_shell", None]
            ]
        )
        == "1 vật dùng bề mặt ObjectGS; 1 vật dùng cách cũ (vỏ Gaussian)"
    )


@pytest.mark.parametrize(
    "accepted,count,stale,expected",
    [
        (False, 4, False, "Chờ bạn duyệt 4 vùng đã che"),
        (True, 4, False, "Đã che 4 vùng (mặt, biển số); bạn đã chấp nhận"),
        (True, 0, False, "Không có vùng cần che; hệ thống đã kiểm tra"),
        (True, 4, True, None),
    ],
)
def test_progress_redaction_note_is_bound_to_review(
    monkeypatch: pytest.MonkeyPatch, accepted: bool, count: int, stale: bool, expected: str | None
) -> None:
    base = job()
    records = [
        StageArtifact(
            stage_id=StageId.FRAME_EXTRACT,
            status="SUCCEEDED",
            artifact_type="NormalizedRGBFrameSet",
            artifact_uri=f"artifact://jobs/{base.job_id}/rec02a/sanitized/frame_set.json",
            artifact_checksum="sha256:" + "a" * 64,
            data_class="derived",
            completed_at=base.started_at,
        )
    ]
    if accepted:
        records.append(
            records[0].model_copy(update={"stage_id": StageId.PRIVACY_GATE, "artifact_type": "SanitizationAcceptance"})
        )
    base = base.model_copy(update={"stage_artifacts": records, "status": JobStatus.QUEUED})
    monkeypatch.setattr(stage_results, "recorded_results", lambda *_: {})
    monkeypatch.setattr(stage_results, "_redaction_summary", lambda *_: (count, "frames", "manifest"))
    monkeypatch.setattr(
        stage_results,
        "_read",
        lambda *_: {"frame_set_checksum": "stale" if stale else "frames", "sanitization_manifest_checksum": "manifest"},
    )
    notes = stage_results.stage_notes(SimpleNamespace(runtime_resolver=None), base)
    assert notes.get(StageId.FRAME_EXTRACT) == expected


def test_progress_small_receipts_are_cached_by_checksum(tmp_path: Path) -> None:
    from src.services.orchestration.artifacts import ArtifactResolver, sha256_file

    path = tmp_path / "jobs/j/e.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"n": 1}))
    resolver = ArtifactResolver(tmp_path)
    uri = "artifact://jobs/j/e.json"
    checksum = sha256_file(path)
    before = stage_results._read.cache_info()
    assert stage_results._read(resolver, uri, checksum) == {"n": 1}
    assert stage_results._read(resolver, uri, checksum) == {"n": 1}
    assert stage_results._read.cache_info().hits == before.hits + 1
    path.write_text(json.dumps({"n": 2}))
    assert stage_results._read(resolver, uri, sha256_file(path)) == {"n": 2}
