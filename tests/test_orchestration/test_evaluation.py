"""Bảng đánh giá: chỉ số lấy đúng từ dữ liệu, bước chưa có kết quả không bị bịa số, báo cáo xuất đúng nội dung."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.models.contracts.scene import SceneIR, SceneObjectOrigin, SceneObjectState
from src.services.orchestration.artifacts import ArtifactNotFoundError
from src.services.orchestration.evaluation import (
    JobEvaluation,
    Metric,
    StageEvaluation,
    evaluate_job,
    evaluation_markdown,
    scorecard,
)
from src.services.orchestration.projects.registry import ProjectRegistry

_ROOT = Path(__file__).resolve().parents[2]
_GEOMETRY = _ROOT / "configs" / "product" / "geometry_v1.json"


def _scene(reviews: list[tuple[str, str | None]]) -> SceneIR:
    """SceneIR fixture với danh sách vật `(origin, review)`; review None = chưa duyệt."""
    scene = SceneIR.model_validate_json((_ROOT / "fixtures" / "scene_ir" / "scene.json").read_text())
    template = scene.objects[0]
    objects = []
    for index, (origin, review) in enumerate(reviews):
        name = f"object-{index:03d}"
        provenance = {**template.provenance, **({"review": review} if review else {})}
        objects.append(
            template.model_copy(
                update={
                    "id": name,
                    "local_frame": name,
                    "origin": SceneObjectOrigin(origin),
                    "state": SceneObjectState.CONFIRMED if review == "CONFIRMED" else SceneObjectState.CANDIDATE,
                    "transform": template.transform.model_copy(update={"local_frame": name}),
                    "provenance": provenance,
                },
                deep=True,
            )
        )
    return scene.model_copy(update={"objects": objects})


def _values(metrics: list[Metric]) -> dict[str, object]:
    return {metric.key: metric.value for metric in metrics}


def test_object_metrics_use_the_reviewers_decisions() -> None:
    scene = _scene(
        [("reconstructed", "CONFIRMED")] * 3
        + [("reconstructed", "IGNORED"), ("reconstructed", "DELETED")]
        + [("reconstructed", None)] * 5
        + [("user_added", None)] * 2
    )
    metrics = scorecard._object_metrics(scene)
    assert metrics is not None
    assert _values(metrics) == {
        "objects.precision": 60.0,  # 3 xác nhận trên 5 vật đã duyệt
        "objects.reviewed": 50.0,  # 5 trên 10 vật máy đề xuất
        "objects.user_added": 2,
        "objects.proposed": 10,
    }
    assert "còn 5 chưa duyệt" in next(m.display for m in metrics if m.key == "objects.reviewed")


def test_object_precision_is_unknown_until_something_is_reviewed() -> None:
    metrics = scorecard._object_metrics(_scene([("reconstructed", None)] * 4))
    assert metrics is not None
    precision = next(metric for metric in metrics if metric.key == "objects.precision")
    assert precision.value is None and precision.display == "Chưa có vật nào được duyệt"
    assert scorecard._object_metrics(None) is None


def test_group_distinguishes_not_run_from_unreadable() -> None:
    def broken() -> list[Metric]:
        raise ArtifactNotFoundError("mất file")

    assert scorecard._group("g", "Nhóm", lambda: None).status == "pending"
    unreadable = scorecard._group("g", "Nhóm", broken)
    assert unreadable.status == "unavailable" and unreadable.metrics == []
    measured = scorecard._group("g", "Nhóm", lambda: [Metric(key="k", label="L", value=1, display="1", meaning="m")])
    assert measured.status == "measured" and len(measured.metrics) == 1


def test_job_without_results_reports_every_group_as_pending(tmp_path: Path) -> None:
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    job = registry.create_job(SimpleNamespace(project_id="project-fixture-001", scene_revision="rev-001"))

    evaluation = evaluate_job(registry, job.job_id, _GEOMETRY)

    assert evaluation.job_id == job.job_id and evaluation.job_status == "QUEUED"
    assert [group.group_id for group in evaluation.groups] == [
        "ST-INPUT-VALIDATE",
        "ST-CAMERA-POSE",
        "ST-VISUAL-RECON",
        "ST-METRIC-CANONICALIZE",
        "ST-RGB-GEOMETRY",
        "ST-OBJECT-EXTRACT",
        "system",
    ]
    assert {group.status for group in evaluation.groups} == {"pending"}
    assert all(group.metrics == [] for group in evaluation.groups)


def _evaluation() -> JobEvaluation:
    return JobEvaluation(
        job_id="job-1",
        project_id="project-1",
        scene_name="Kho | A",
        job_status="SUCCEEDED",
        scene_revision="rev-002",
        generated_at=datetime(2026, 10, 2, 3, 0, tzinfo=UTC),
        groups=[
            StageEvaluation(
                group_id="ST-CAMERA-POSE",
                title="Vị trí camera",
                status="measured",
                metrics=[
                    Metric(
                        key="pose.registered_ratio",
                        label="Ảnh dựng được",
                        value=96.0,
                        unit="%",
                        display="96.0 % (48/50)",
                        meaning="Phần ảnh | có vị trí",
                        verdict="ok",
                        threshold="≥ 50%",
                    ),
                    Metric(key="pose.error", label="Sai số", value=None, display="Chưa đo", meaning="Lệch pixel"),
                ],
            ),
            StageEvaluation(
                group_id="ST-RGB-GEOMETRY", title="Hình học", status="pending", note="Bước này chưa có kết quả."
            ),
        ],
    )


def test_markdown_report_carries_values_verdicts_and_unmeasured_steps() -> None:
    report = evaluation_markdown(_evaluation())
    assert report.startswith("# Đánh giá scene: Kho | A\n")
    assert "`job-1` · trạng thái SUCCEEDED · revision `rev-002`" in report
    assert "| Ảnh dựng được | 96.0 % (48/50) | Đạt (≥ 50%) | Phần ảnh \\| có vị trí |" in report
    assert "| Sai số | Chưa đo | — | Lệch pixel |" in report
    assert "## Hình học\n\n_Chưa có kết quả._ Bước này chưa có kết quả." in report
    assert "không so với ground truth" in report


@pytest_asyncio.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    from src.api import auth
    from src.api.studio import deps
    from src.main import app

    settings = SimpleNamespace(
        auth_required=False, database_url=f"sqlite:///{tmp_path / 'runtime.db'}", product_geometry_config=_GEOMETRY
    )
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_project_registry", lambda: registry)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_evaluation_routes_return_scorecard_and_downloadable_report(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/jobs/khong-co/evaluation")).status_code == 404
    assert (await client.get("/api/v1/jobs/khong-co/evaluation/report.md")).status_code == 404

    response = await client.get("/api/v1/jobs/job-fixture-001/evaluation")
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job-fixture-001" and len(body["groups"]) == 7
    assert all(group["status"] in {"measured", "pending", "unavailable"} for group in body["groups"])

    report = await client.get("/api/v1/jobs/job-fixture-001/evaluation/report.md")
    assert report.status_code == 200 and report.headers["content-type"].startswith("text/markdown")
    assert report.headers["content-disposition"] == 'attachment; filename="evaluation-job-fixture-001.md"'
    assert report.text.startswith("# Đánh giá scene:")


def test_held_out_quality_reports_scores_or_the_reason_it_is_missing() -> None:
    """PSNR/SSIM/LPIPS chỉ hiện khi đã đo trên ảnh giữ lại; thiếu thì nêu lý do, không điền số."""
    from src.services.orchestration.evaluation.scorecard import _held_out_metrics
    from src.services.reconstruction import VisualQuality

    base = dict(gaussians=1000, nonfinite_values=0, training_frames=44, train_iterations=30000)

    old_scene = _held_out_metrics(VisualQuality(**base))
    assert [metric.key for metric in old_scene] == ["visual.novel_view_quality"]
    assert old_scene[0].value is None and "train trên mọi ảnh" in old_scene[0].display

    no_report = _held_out_metrics(VisualQuality(**base, held_out_frames=6))
    assert no_report[0].value is None and "không in kết quả" in no_report[0].display

    measured = _held_out_metrics(
        VisualQuality(**base, held_out_frames=6, held_out_psnr=28.6165, held_out_ssim=0.89637, held_out_lpips=None)
    )
    by_key = {metric.key: metric for metric in measured}
    assert by_key["visual.novel_view_quality"].value == 28.62 and by_key["visual.novel_view_quality"].unit == "dB"
    assert "6 ảnh giữ lại" in by_key["visual.novel_view_quality"].display
    assert by_key["visual.novel_view_ssim"].value == 0.8964
    assert (
        by_key["visual.novel_view_lpips"].value is None and "chưa cấu hình" in by_key["visual.novel_view_lpips"].display
    )

    with_lpips = _held_out_metrics(
        VisualQuality(**base, held_out_frames=6, held_out_psnr=28.0, held_out_ssim=0.9, held_out_lpips=0.26495)
    )
    assert with_lpips[2].value == pytest.approx(0.265, abs=1e-3)
    assert "VGG" in with_lpips[2].display


def test_reference_group_appears_only_after_an_evaluator_recorded_results(tmp_path: Path) -> None:
    import json

    from eval.reference.torwic import base_record, write_record

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    job = registry.create_job(SimpleNamespace(project_id="project-fixture-001", scene_revision="rev-001"))
    assert "reference" not in [group.group_id for group in evaluate_job(registry, job.job_id, _GEOMETRY).groups]

    traversal = Path("Aisle_CW")
    pose = base_record("recon_pose", "unit-test", job.job_id, traversal, 0) | {
        "job_used_this_trajectory": True,
        "registered_frames": 40,
        "path_length_m": 12.5,
        "ate_similarity_m": {"rmse": 0.5},
        "rpe_translation_m": {"p50": 0.02},
        "rpe_rotation_deg": {"p50": 0.4},
    }
    write_record(registry, pose, tmp_path / "results" / "recon_pose" / "unit-test.jsonl")
    # Lượt chấm sau thay lượt trước trong bảng; bản ghi cũ vẫn còn nguyên.
    second = write_record(registry, pose | {"ate_similarity_m": {"rmse": 0.081}}, None)
    assert second.artifact_uri.endswith("/benchmark/recon_pose/attempt-2.json")
    scale = base_record("metric_scale", "unit-test", job.job_id, traversal, 0)
    write_record(registry, scale | {"job_used_this_trajectory": False, "scale_error_percent": -1.25}, None)

    proposal = base_record("metric_scale_proposal", "unit-test", job.job_id, traversal, 0)
    proposal |= {"proposal_method": "moge2_sparse_depth_scale_only", "proposal_error_percent": -0.24}
    write_record(registry, proposal | {"scale_is_independent": True}, None)

    group = next(g for g in evaluate_job(registry, job.job_id, _GEOMETRY).groups if g.group_id == "reference")
    values = _values(group.metrics)
    assert group.status == "measured" and "ground truth" in (group.note or "")
    assert values["reference.ate"] == 8.1 and values["reference.scale_error"] == -1.25
    assert {metric.source for metric in group.metrics} == {"reference"}
    assert values["reference.scale_proposal_error"] == -0.24
    assert "reference.surface_accuracy" not in values
    ate = next(metric for metric in group.metrics if metric.key == "reference.ate")
    assert "không phải độ chính xác độc lập" in ate.meaning
    lines = (tmp_path / "results" / "recon_pose" / "unit-test.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["assistance"] == "evaluation_only_ground_truth"


def test_reference_label_must_follow_the_benchmark_naming_rule() -> None:
    from eval.reference.torwic import base_record

    with pytest.raises(ValueError, match="nhãn"):
        base_record("recon_pose", "Nhãn Sai", "job-x", Path("Aisle_CW"), 0)


def test_lidar_group_reports_the_ingested_package(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    record = SimpleNamespace(
        kind="lidar_scan_sequence",
        point_count=1000,
        pose_count=50,
        floor_support_points=300,
        trajectory_origin="estimated",
        fusion=SimpleNamespace(scan_count=10, removed_points=250, input_points=1000),
    )
    path = tmp_path / "record.json"
    path.write_text("{}")
    monkeypatch.setattr(scorecard, "_reference", lambda *_args: object())
    monkeypatch.setattr(scorecard.LidarPackageRecord, "model_validate_json", classmethod(lambda _cls, _raw: record))
    registry = SimpleNamespace(runtime_resolver=SimpleNamespace(require=lambda _ref: path))

    values = _values(scorecard._lidar_metrics(registry, SimpleNamespace()))  # type: ignore[arg-type]

    assert values["lidar.scans"] == 10 and values["lidar.removed_points"] == 25.0
    assert values["lidar.points"] == 1000 and values["lidar.trajectory_origin"] == "estimated"

    record.fusion = None
    record.kind = "registered_lidar"
    registered = _values(scorecard._lidar_metrics(registry, SimpleNamespace()))  # type: ignore[arg-type]
    assert "lidar.scans" not in registered and registered["lidar.kind"] == "registered_lidar"
