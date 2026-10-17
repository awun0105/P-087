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


def test_progress_reads_verify_checksum_without_caching_documents(tmp_path: Path) -> None:
    from src.services.orchestration.artifacts import ArtifactResolver, ArtifactStoreError, sha256_file

    path = tmp_path / "jobs/j/e.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"n": 1}))
    resolver = ArtifactResolver(tmp_path)
    uri = "artifact://jobs/j/e.json"
    checksum = sha256_file(path)
    assert stage_results._read(resolver, uri, checksum) == {"n": 1}
    path.write_text(json.dumps({"n": 2}))
    with pytest.raises(ArtifactStoreError):
        stage_results._read(resolver, uri, checksum)
    assert stage_results._read(resolver, uri, sha256_file(path)) == {"n": 2}
    assert not hasattr(stage_results._read, "cache_info")


def test_progress_scene_cache_keeps_only_bounded_summaries_for_300_revisions(tmp_path: Path) -> None:
    from src.services.orchestration.artifacts import ArtifactResolver, sha256_file

    path = tmp_path / "jobs/j/scene.json"
    path.parent.mkdir(parents=True)
    resolver = ArtifactResolver(tmp_path)
    ref = SimpleNamespace(artifact_uri="artifact://jobs/j/scene.json", artifact_checksum="")
    ref.model_dump = lambda: {"artifact_uri": ref.artifact_uri, "artifact_checksum": ref.artifact_checksum}
    registry = SimpleNamespace(
        runtime_resolver=resolver,
        persistence=None,
        scene=SimpleNamespace(head_repository=SimpleNamespace(get=lambda _: SimpleNamespace(scene_reference=ref))),
    )
    base = job().model_copy(update={"stage_artifacts": []})
    scene = {
        "objects": [
            {
                "origin": "reconstructed",
                "collider": {},
                "provenance": {"surface_selection": {"chosen": "objectgs"}},
                "unused": "x" * 2000,
            }
            for _ in range(400)
        ],
        "environment": {},
        "provenance": {"object_geometry": "ready", "object_extraction": "complete"},
    }
    for revision in range(300):
        scene["scene_revision"] = f"rev-{revision}"
        path.write_text(json.dumps(scene))
        ref.artifact_checksum = sha256_file(path)
        assert stage_results.stage_notes(registry, base) == {StageId.OBJECT_EXTRACT: "400 vật ứng viên"}
    summary_cache = stage_results._scene_summary
    assert summary_cache.cache_info().maxsize == 256
    assert summary_cache.cache_info().currsize <= 256
    summary = summary_cache(resolver, ref.artifact_uri, ref.artifact_checksum)

    def immutable(value: object) -> bool:
        return isinstance(value, (str, int, float, type(None))) or (
            isinstance(value, tuple) and all(immutable(item) for item in value)
        )

    assert isinstance(summary, tuple) and immutable(summary)
    assert summary.scene_revision == "rev-299"
    assert len(repr(summary)) < 10000
    assert not hasattr(stage_results._read, "cache_info")
    assert stage_results.recorded_results(registry, base)["object_geometry"] == {
        "state": "succeeded",
        "duration_seconds": None,
        "objectgs_count": 400,
        "shell_count": 0,
        "collider_count": 400,
    }


def test_progress_redaction_cache_uses_small_checksum_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.services.orchestration.jobs import anonymization_review

    base = job()
    sanitized = StageArtifact(
        stage_id=StageId.FRAME_EXTRACT,
        status="SUCCEEDED",
        artifact_type="NormalizedRGBFrameSet",
        artifact_uri=f"artifact://jobs/{base.job_id}/rec02a/sanitized/frame_set.json",
        artifact_checksum="sha256:" + "a" * 64,
        data_class="derived",
        completed_at=base.started_at,
    )
    base = base.model_copy(update={"stage_artifacts": [sanitized], "status": JobStatus.QUEUED})
    loads = []

    def load(registry: object, current: JobManifest) -> tuple:
        loads.append(current)
        return SimpleNamespace(frame_set_checksum="frames"), SimpleNamespace(
            frames=[SimpleNamespace(regions=[1, 2])], manifest_checksum="manifest"
        )

    monkeypatch.setattr(anonymization_review, "_load", load)
    monkeypatch.setattr(stage_results, "recorded_results", lambda *_: {})
    monkeypatch.setattr(JobManifest, "model_dump_json", lambda *_: pytest.fail("Không dùng cả job làm khóa cache"))
    registry = type("Registry", (), {"get_job": lambda self, _: base})()
    stage_results._redaction_summary.cache_clear()
    assert stage_results.stage_notes(registry, base)[StageId.FRAME_EXTRACT] == "Chờ bạn duyệt 2 vùng đã che"
    base = base.model_copy(update={"job_manifest_checksum": "sha256:" + "c" * 64})
    assert stage_results.stage_notes(registry, base)[StageId.FRAME_EXTRACT] == "Chờ bạn duyệt 2 vùng đã che"
    assert len(loads) == 1
    sanitized = sanitized.model_copy(update={"artifact_checksum": "sha256:" + "b" * 64})
    base = base.model_copy(update={"stage_artifacts": [sanitized]})
    assert stage_results.stage_notes(registry, base)[StageId.FRAME_EXTRACT] == "Chờ bạn duyệt 2 vùng đã che"
    assert len(loads) == 2


@pytest.mark.parametrize("kind", ["metric", "collision"])
def test_progress_receipt_caches_keep_scalar_tuples_and_refresh_by_checksum(tmp_path: Path, kind: str) -> None:
    from src.services.orchestration.artifacts import ArtifactResolver, sha256_file

    root = tmp_path / "jobs/j"
    root.mkdir(parents=True)
    path = root / "receipt.json"
    uri = "artifact://jobs/j/receipt.json"
    resolver = ArtifactResolver(tmp_path)
    if kind == "metric":
        declaration = root / "declaration.json"
        declaration.write_text(
            json.dumps(
                {
                    "job_id": "j",
                    "input": {
                        "distance_source": "user_measured",
                        "check_a": [0, 0, 0],
                        "check_b": [1, 0, 0],
                        "check_distance_m": 2,
                    },
                }
            )
        )
        document = {
            "preview": {
                "request": {
                    "anchor": {
                        "measurement_ref": {
                            "artifact_uri": "artifact://jobs/j/declaration.json",
                            "artifact_checksum": sha256_file(declaration),
                        }
                    }
                },
                "transform": {"scale_m_per_sfm_unit": 2},
            }
        }
        cache = stage_results._metric_summary
        extra = ("j",)
    else:
        document = {
            "canonical_geometry_ref": {
                "artifact_type": "LidarCollisionCandidate",
                "artifact_uri": "artifact://jobs/j/mesh.glb",
                "artifact_checksum": "sha256:" + "a" * 64,
            }
        }
        cache = stage_results._collision_summary
        extra = ()
    cache.cache_clear()
    path.write_text(json.dumps(document))
    checksum = sha256_file(path)
    summary = cache(resolver, uri, checksum, *extra)
    assert isinstance(summary, tuple)
    assert cache(resolver, uri, checksum, *extra) == summary
    assert cache.cache_info().hits == 1
    assert cache.cache_info().maxsize == 256
    # Không giữ dict receipt, kể cả các field dư không dùng trong tiến trình.
    document["unused"] = {"large": "x" * 20000}
    path.write_text(json.dumps(document))
    assert cache(resolver, uri, sha256_file(path), *extra) == summary
    assert cache.cache_info().misses == 2
    assert len(repr(summary)) < 1000
    assert all(not isinstance(item, dict) for item in summary)


def test_progress_contract_mirror_detects_a_missing_note() -> None:
    from scripts.check_contract_mirror import _check_models
    from src.services.orchestration.jobs.progress import StageProgress

    source = Path("frontend/src/lib/contracts/studio.ts").read_text()
    assert _check_models(source, [("StageProgress", StageProgress)]) == []
    assert "StageProgress.note: có trong Pydantic, thiếu ở TypeScript" in _check_models(
        source.replace("  note?: string | null;", ""), [("StageProgress", StageProgress)]
    )
