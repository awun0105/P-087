"""Bảng đánh giá: chỉ số lấy đúng từ dữ liệu, bước chưa có kết quả không bị bịa số, báo cáo xuất đúng nội dung."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.models.contracts.manifests import JobStatus, StageArtifact, StageId
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
from src.services.orchestration.evaluation.advice import summarize
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.reconstruction.quality import GeometryProfileMismatchError

_ROOT = Path(__file__).resolve().parents[2]
_GEOMETRY = _ROOT / "configs" / "product" / "geometry_v1.json"
_EVALUATION_REFERENCE = _ROOT / "configs" / "product" / "evaluation_reference_v1.json"


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

    def stale_profile() -> list[Metric]:
        raise GeometryProfileMismatchError("thông số hình học của deployment khác bản đã dùng để dựng mesh của job")

    # Mesh vẫn đọc được: lý do phải nói đúng là thông số đã đổi, không phải artifact hỏng.
    stale = scorecard._group("g", "Nhóm", stale_profile)
    assert stale.status == "unavailable" and stale.metrics == []
    assert stale.note != unreadable.note and "dựng lại" in stale.note
    measured = scorecard._group("g", "Nhóm", lambda: [Metric(key="k", label="L", value=1, display="1", meaning="m")])
    assert measured.status == "measured" and len(measured.metrics) == 1


def test_job_without_results_keeps_stages_pending_and_reports_missing_resource_data(tmp_path: Path) -> None:
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
    system = next(group for group in evaluation.groups if group.group_id == "system")
    other_groups = [group for group in evaluation.groups if group.group_id != "system"]
    assert {group.status for group in other_groups} == {"pending"}
    assert all(group.metrics == [] for group in other_groups)
    assert system.status == "measured"
    assert {metric.key for metric in system.metrics} == {"system.peak_ram", "system.peak_vram", "system.config"}
    assert all(metric.value is None for metric in system.metrics)
    assert all(metric.display == "Chưa đo — job này không có bản ghi tài nguyên" for metric in system.metrics)
    assert evaluation.summary == []


def _evaluation() -> JobEvaluation:
    return JobEvaluation(
        job_id="job-1",
        project_id="project-1",
        scene_name="Kho | A",
        job_status="SUCCEEDED",
        scene_revision="rev-002",
        generated_at=datetime(2026, 10, 2, 3, 0, tzinfo=UTC),
        summary=["Đề xuất thứ nhất", "Cảnh báo | dòng\n2"],
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
                    Metric(
                        key="pose.error",
                        label="Sai số",
                        value=None,
                        display="Chưa đo",
                        meaning="Lệch pixel",
                        reference="Các scene đã chạy: 25,35–30,00 dB (6 scene)",
                    ),
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
    assert "| Chỉ số | Giá trị | Tham chiếu | Kết luận | Ý nghĩa |" in report
    assert "| Ảnh dựng được | 96.0 % (48/50) |  | Đạt (≥ 50%) | Phần ảnh \\| có vị trí |" in report
    assert "| Sai số | Chưa đo | Các scene đã chạy: 25,35–30,00 dB (6 scene) | — | Lệch pixel |" in report
    assert "## Hình học\n\n_Chưa có kết quả._ Bước này chưa có kết quả." in report
    assert "không so với ground truth" in report
    assert report.index("- Đề xuất thứ nhất") < report.index("## Vị trí camera")
    assert "- Cảnh báo \\| dòng 2" in report


@pytest_asyncio.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    from src.api import auth
    from src.api.studio import deps
    from src.main import app

    settings = SimpleNamespace(
        auth_required=False,
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        product_geometry_config=_GEOMETRY,
        product_evaluation_reference=_EVALUATION_REFERENCE,
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
    system = next(group for group in body["groups"] if group["group_id"] == "system")
    assert {metric["key"] for metric in system["metrics"]} >= {
        "system.peak_ram",
        "system.peak_vram",
        "system.config",
    }


@pytest.mark.asyncio
async def test_evaluation_route_survives_resource_database_read_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import sqlite3

    from src.api.studio import evaluation as evaluation_api

    def unreadable(_database: object) -> list[object]:
        raise sqlite3.OperationalError("database is unavailable")

    monkeypatch.setattr(evaluation_api, "load_usages", unreadable)
    response = await client.get("/api/v1/jobs/job-fixture-001/evaluation")

    assert response.status_code == 200
    system = next(group for group in response.json()["groups"] if group["group_id"] == "system")
    assert all(metric["value"] is None for metric in system["metrics"] if metric["key"].startswith("system.peak_"))
    assert "Không đọc được bản ghi tài nguyên của job" in caplog.text


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
    assert all(metric.reference is None and metric.verdict is None for metric in with_lpips)


def test_held_out_reference_ranges_are_descriptive_and_never_verdicts() -> None:
    from src.services.orchestration.evaluation.reference import describe, load_reference
    from src.services.reconstruction import VisualQuality

    reference = load_reference(_EVALUATION_REFERENCE)
    assert reference is not None
    assert describe([25.35, 25.49, 26.36, 28.45, 28.8, 30.0], "dB", 2) == (
        "Các scene đã chạy: 25,35–30,00 dB (6 scene)"
    )
    assert describe([25.35], "dB", 2) is None
    lpips = [scene.lpips for scene in reference.scenes if scene.lpips is not None]
    assert describe(lpips, "", 3) == "Các scene đã chạy: 0,268–0,344 (5 scene)"

    metrics = scorecard._held_out_metrics(
        VisualQuality(
            gaussians=1000,
            nonfinite_values=0,
            training_frames=44,
            train_iterations=30000,
            held_out_frames=6,
            held_out_psnr=28.6165,
            held_out_ssim=0.89637,
            held_out_lpips=0.26495,
        ),
        reference,
    )
    by_key = {metric.key: metric for metric in metrics}
    assert by_key["visual.novel_view_quality"].value == 28.62
    assert by_key["visual.novel_view_quality"].reference == "Các scene đã chạy: 25,35–30,00 dB (6 scene)"
    assert by_key["visual.novel_view_ssim"].reference == "Các scene đã chạy: 0,888–0,939 (6 scene)"
    assert by_key["visual.novel_view_lpips"].reference == "Các scene đã chạy: 0,268–0,344 (5 scene)"
    assert all(metric.verdict is None for metric in metrics)


def test_invalid_or_missing_evaluation_reference_warns_and_falls_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from src.services.orchestration.evaluation.reference import load_reference

    assert load_reference(None) is None
    assert load_reference(tmp_path / "missing.json") is None
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"schema_version":"2.0","note":"bad","scenes":[]}', encoding="utf-8")
    assert load_reference(invalid) is None
    assert "Không đọc được file tham chiếu đánh giá" in caplog.text


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


def test_advice_summary_rules_and_ordering() -> None:
    from src.services.orchestration.evaluation.advice import summarize

    g_input = StageEvaluation(
        group_id="input",
        title="Input",
        status="measured",
        metrics=[
            Metric(
                key="input.warnings",
                label="Cảnh báo chuyển động",
                value=2,
                display="đứng yên lâu",
                meaning="m",
                verdict="warn",
                threshold="upload_quality_v2.json",
            )
        ],
    )
    g_pose = StageEvaluation(
        group_id="pose",
        title="Pose",
        status="measured",
        metrics=[
            Metric(
                key="pose.registered_ratio",
                label="Tỷ lệ",
                value=30.0,
                display="30%",
                meaning="m",
                verdict="fail",
                threshold="≥ 50%",
            )
        ],
    )
    g_visual = StageEvaluation(
        group_id="visual",
        title="Visual",
        status="measured",
        metrics=[
            Metric(
                key="visual.nonfinite_values",
                label="Giá trị hỏng",
                value=5,
                display="5",
                meaning="m",
                verdict="fail",
                threshold="0",
            )
        ],
    )
    g_metric = StageEvaluation(
        group_id="metric",
        title="Metric",
        status="measured",
        metrics=[
            Metric(
                key="metric.check_error",
                label="Sai số đoạn kiểm",
                value=8.0,
                display="8,0%",
                meaning="m",
                verdict="warn",
                threshold="≤ 5%",
            )
        ],
    )
    summary = summarize([g_input, g_pose, g_visual, g_metric])
    assert len(summary) == 4
    assert (
        summary[0]
        == "COLMAP chỉ dựng được vị trí cho 30% ảnh, dưới ngưỡng ≥ 50%. Quay chậm hơn và để các khung hình liên tiếp chồng lấn nhiều hơn."
    )
    assert summary[1] == "File 3DGS có giá trị hỏng. Chạy lại bước dựng hình; không duyệt scene này."
    assert (
        summary[2]
        == "Video có cảnh báo chuyển động: đứng yên lâu. Lần quay sau hãy di chuyển đều tay, tránh đứng yên lâu hoặc lia máy nhanh."
    )
    assert (
        summary[3] == "Đoạn kiểm C–D lệch 8,0%, ngoài ngưỡng ≤ 5%. Đo lại hai đoạn A–B và C–D rồi xác nhận lại tỉ lệ."
    )

    g_metric_fail = StageEvaluation(
        group_id="metric",
        title="Metric",
        status="measured",
        metrics=[
            Metric(
                key="metric.check_error",
                label="Sai số đoạn kiểm",
                value=15.0,
                display="15,0%",
                meaning="m",
                verdict="fail",
                threshold="≤ 5%",
            )
        ],
    )
    assert summarize([g_metric_fail]) == [
        "Đoạn kiểm C–D lệch 15,0%, ngoài ngưỡng ≤ 5%. Đo lại hai đoạn A–B và C–D rồi xác nhận lại tỉ lệ."
    ]

    g_custom = StageEvaluation(
        group_id="custom",
        title="Custom",
        status="measured",
        metrics=[
            Metric(
                key="custom.metric",
                label="Chỉ số tùy chỉnh",
                value=10,
                display="10 điểm",
                meaning="m",
                verdict="warn",
                threshold="≤ 5 điểm",
            )
        ],
    )
    assert summarize([g_custom]) == ["Chỉ số tùy chỉnh: 10 điểm (ngưỡng: ≤ 5 điểm)"]

    g_ok = StageEvaluation(
        group_id="ok_group",
        title="OK",
        status="measured",
        metrics=[
            Metric(key="m1", label="M1", value=1, display="1", meaning="m", verdict="ok", threshold="> 0"),
            Metric(key="m2", label="M2", value=2, display="2", meaning="m"),
        ],
    )
    ok_summary = summarize([g_ok])
    assert ok_summary == [
        "Không có chỉ số tự kiểm nào dưới ngưỡng. 1 trên 2 chỉ số có ngưỡng; các chỉ số còn lại chỉ để tham khảo."
    ]

    g_unknown_without_threshold = StageEvaluation(
        group_id="unknown",
        title="Unknown",
        status="measured",
        metrics=[Metric(key="custom.metric", label="Chỉ số", value=1, display="1", meaning="m", verdict="warn")],
    )
    assert summarize([g_unknown_without_threshold]) == ["Chỉ số: 1 (ngưỡng: chưa ghi ngưỡng)"]

    for s in [*summary, *ok_summary]:
        assert "sẵn sàng" not in s.lower()


def test_system_resource_metrics(tmp_path: Path) -> None:
    from src.services.orchestration.processing.telemetry import ResourceUsage

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    job = registry.create_job(SimpleNamespace(project_id="project-fixture-001", scene_revision="rev-001"))
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

    def make_usage(
        tool: str,
        ram: float | None,
        vram: float | None,
        job_id: str | None = None,
        outcome: str = "completed",
        completed_at: datetime = now,
        params: dict[str, float] | None = None,
        shared_gpu: bool | None = None,
        gpu_used_before_gb: float | None = None,
        peak_gpu_used_gb: float | None = None,
    ) -> ResourceUsage:
        return ResourceUsage(
            schema_version="1.2",
            job_id=job_id or job.job_id,
            attempt_id="att1",
            tool=tool,
            config_checksum="c",
            runtime_manifest_checksum="r",
            params=params,
            started_at=now,
            completed_at=completed_at,
            outcome=outcome,
            exit_code=0 if outcome == "completed" else 1,
            duration_seconds=10.0,
            sample_count=1,
            ram_sample_count=1,
            vram_sample_count=1,
            gpu_sample_count=1,
            scratch_sample_count=1,
            peak_ram_gb=ram,
            peak_vram_gb=vram,
            shared_gpu=shared_gpu,
            gpu_used_before_gb=gpu_used_before_gb,
            peak_gpu_used_gb=peak_gpu_used_gb,
            headroom_before={},
        )

    u_preview = make_usage(
        "preview",
        1.5,
        2.0,
        params={"sampling.max_frames": 300.0, "brush.max_splats": 1000000.0, "brush.max_resolution": 1280.0},
    )
    u_scene_extract = make_usage(
        "scene_extract",
        5.1937,
        None,
        completed_at=datetime(2026, 10, 5, 12, 10, tzinfo=UTC),
        params={"sampling.max_frames": 1200.0, "brush.max_splats": 6000000.0, "brush.max_resolution": 3840.0},
        shared_gpu=False,
        gpu_used_before_gb=1.0,
        peak_gpu_used_gb=4.4179,
    )
    u_failed = make_usage("scene_extract", 10.0, 10.0, outcome="failed")
    u_other_job = make_usage("scene_extract", 20.0, 20.0, job_id="job-other")

    usages = [u_preview, u_scene_extract, u_failed, u_other_job]
    metrics = scorecard._system_metrics(registry, job, usages)
    by_key = {metric.key: metric for metric in metrics}

    ram_m = by_key["system.peak_ram"]
    assert ram_m.value == 5.19
    assert ram_m.display == "5,2 GB (bước scene_extract)"

    vram_m = by_key["system.peak_vram"]
    assert vram_m.value == 3.42
    assert vram_m.display == "3,4 GB (bước scene_extract)"

    config_m = by_key["system.config"]
    assert config_m.value is None
    assert config_m.display == "tối đa 1.200 frame · 6.000.000 splat · 3.840 px"

    no_measurement = scorecard._system_metrics(registry, job)
    assert {metric.key for metric in no_measurement} == {"system.peak_ram", "system.peak_vram", "system.config"}
    assert all(metric.value is None for metric in no_measurement)
    assert all(metric.display == "Chưa đo — job này không có bản ghi tài nguyên" for metric in no_measurement)


def test_scene_operations_leave_the_pipeline_resource_metrics_unchanged(tmp_path: Path) -> None:
    """Tạo mesh và dựng lại vùng (`scene.*`) không đổi thẻ RAM/VRAM/cấu hình của lượt chạy pipeline."""
    from src.services.orchestration.processing.telemetry import ResourceUsage

    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    job = registry.create_job(SimpleNamespace(project_id="project-fixture-001", scene_revision="rev-001"))
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    later = now + timedelta(minutes=30)

    def usage(tool: str, ram: float, vram: float, **changes: object) -> ResourceUsage:
        fields: dict[str, object] = {
            "schema_version": "1.2",
            "job_id": job.job_id,
            "attempt_id": "att1",
            "tool": tool,
            "config_checksum": "c",
            "runtime_manifest_checksum": "r",
            "params": None,
            "started_at": now,
            "completed_at": now,
            "outcome": "completed",
            "exit_code": 0,
            "duration_seconds": 10.0,
            "sample_count": 1,
            "ram_sample_count": 1,
            "vram_sample_count": 1,
            "gpu_sample_count": 1,
            "scratch_sample_count": 1,
            "peak_ram_gb": ram,
            "peak_vram_gb": vram,
            "headroom_before": {},
        }
        return ResourceUsage(**{**fields, **changes})

    params = {"sampling.max_frames": 300.0, "brush.max_splats": 1000000.0, "brush.max_resolution": 1280.0}
    pipeline = [
        usage("preview", 2.0, 1.5, params=params),
        usage("scene_extract", 5.1937, 3.42, params=params, completed_at=later, started_at=later),
    ]
    scene = [
        usage("scene.geometry", 9.5, 7.9, completed_at=later + timedelta(minutes=5)),
        usage("scene.region", 8.0, 6.0, outcome="failed", completed_at=later + timedelta(minutes=6)),
    ]

    def cards(usages: list[ResourceUsage]) -> list[tuple[str, object, str]]:
        return [(m.key, m.value, m.display) for m in scorecard._system_metrics(registry, job, usages)]

    baseline = cards(pipeline)
    assert ("system.peak_ram", 5.19, "5,2 GB (bước scene_extract)") in baseline
    assert cards(pipeline + scene) == baseline


def _timed_stage(stage_id: StageId, started_at: datetime, completed_at: datetime) -> StageArtifact:
    return StageArtifact(
        stage_id=stage_id,
        status="SUCCEEDED",
        artifact_type="TimingFixture",
        artifact_uri=f"artifact://jobs/job-timing/{stage_id.value.lower()}.json",
        artifact_checksum="sha256:" + "a" * 64,
        data_class="derived",
        started_at=started_at,
        completed_at=completed_at,
    )


def _timing_event(
    attempt: int,
    status: JobStatus,
    stage_id: StageId,
    recorded_at: datetime,
    *,
    stage_started_at: datetime | None = None,
) -> JobAttemptRecord:
    return JobAttemptRecord(
        attempt=attempt,
        status=status,
        current_stage=stage_id,
        recorded_at=recorded_at,
        stage_started_at=stage_started_at,
    )


def test_system_processing_time_excludes_metric_confirmation_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    job = registry.create_job(SimpleNamespace(project_id="project-fixture-001", scene_revision="rev-001"))
    start = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    visual_start = start + timedelta(seconds=1)
    visual_end = visual_start + timedelta(seconds=10)
    metric_start = visual_end
    metric_end = metric_start + timedelta(hours=14, minutes=30)
    geometry_start = metric_end + timedelta(seconds=5)
    geometry_end = geometry_start + timedelta(seconds=30)
    stages = [
        _timed_stage(StageId.VISUAL_RECON, visual_start, visual_end),
        _timed_stage(StageId.METRIC_CANONICALIZE, metric_start, metric_end),
        _timed_stage(StageId.RGB_GEOMETRY, geometry_start, geometry_end),
    ]
    attempts = [
        _timing_event(1, JobStatus.QUEUED, StageId.INPUT_VALIDATE, start),
        _timing_event(1, JobStatus.RUNNING, StageId.VISUAL_RECON, visual_start, stage_started_at=visual_start),
        _timing_event(1, JobStatus.RUNNING, StageId.METRIC_CANONICALIZE, metric_start, stage_started_at=metric_start),
        _timing_event(1, JobStatus.RUNNING, StageId.RGB_GEOMETRY, geometry_start, stage_started_at=geometry_start),
        _timing_event(1, JobStatus.SUCCEEDED, StageId.RGB_GEOMETRY, geometry_end),
    ]
    job = job.model_copy(
        update={
            "status": JobStatus.SUCCEEDED,
            "current_stage": StageId.RGB_GEOMETRY,
            "completed_at": geometry_end,
            "stage_artifacts": stages,
        }
    )
    monkeypatch.setattr(registry, "list_job_attempts", lambda _job_id: attempts)

    metrics = scorecard._system_metrics(registry, job)
    by_key = {metric.key: metric for metric in metrics}

    assert by_key["system.processing_time"].value == 40
    assert by_key["system.slowest_stage"].value == StageId.RGB_GEOMETRY.value


def test_system_processing_time_ignores_stages_reused_from_prior_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    registry.seed_from_fixtures()
    job = registry.create_job(SimpleNamespace(project_id="project-fixture-001", scene_revision="rev-001"))
    retry_at = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    old_start = retry_at - timedelta(hours=3)
    old_visual_start = retry_at - timedelta(hours=1)
    geometry_start = retry_at + timedelta(seconds=10)
    geometry_end = geometry_start + timedelta(seconds=30)
    stages = [
        _timed_stage(StageId.CAMERA_POSE, old_start, old_visual_start),
        _timed_stage(StageId.VISUAL_RECON, old_visual_start, retry_at - timedelta(minutes=5)),
        _timed_stage(StageId.RGB_GEOMETRY, geometry_start, geometry_end),
    ]
    attempts = [
        _timing_event(2, JobStatus.QUEUED, StageId.RGB_GEOMETRY, retry_at),
        _timing_event(2, JobStatus.RUNNING, StageId.RGB_GEOMETRY, geometry_start, stage_started_at=geometry_start),
        _timing_event(2, JobStatus.SUCCEEDED, StageId.RGB_GEOMETRY, geometry_end),
    ]
    job = job.model_copy(
        update={
            "status": JobStatus.SUCCEEDED,
            "current_stage": StageId.RGB_GEOMETRY,
            "completed_at": geometry_end,
            "stage_artifacts": stages,
        }
    )
    monkeypatch.setattr(registry, "list_job_attempts", lambda _job_id: attempts)

    metrics = scorecard._system_metrics(registry, job)
    by_key = {metric.key: metric for metric in metrics}

    assert by_key["system.processing_time"].value == 30
    assert by_key["system.slowest_stage"].value == StageId.RGB_GEOMETRY.value


def test_pose_group_reports_the_retry_ladder_and_a_registration_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-071 C3/D6: mô hình nhận sau thang thử lại là cảnh báo (vùng thiếu ảnh mờ/thủng), không phải lỗi."""
    from src.services.reconstruction.quality import PoseQuality

    base = dict(
        input_frames=100,
        registered_frames=40,
        registered_ratio=0.4,
        min_registered_ratio=0.5,
        sparse_points=4000,
        mean_reprojection_error_px=0.8,
        mean_track_length=4.0,
    )
    measured = {"quality": PoseQuality(**base, retry_steps=2, registration_warning=True, accept_registered_ratio=0.35)}
    monkeypatch.setattr(scorecard, "_reference", lambda *_args: object())
    monkeypatch.setattr(scorecard, "pose_quality", lambda *_args: measured["quality"])
    registry = SimpleNamespace(runtime_resolver=SimpleNamespace(require=lambda _ref: None))

    metrics = {metric.key: metric for metric in scorecard._pose_metrics(registry, SimpleNamespace())}  # type: ignore[arg-type]
    ratio = metrics["pose.registered_ratio"]
    assert ratio.verdict == "warn" and "nhận từ 35%" in (ratio.threshold or "")
    assert metrics["pose.retry_steps"].display == "Đã tự thử lại ghép ảnh (2 lần)"
    advice = summarize(
        [StageEvaluation(group_id="pose", title="Pose", status="measured", metrics=list(metrics.values()))]
    )
    assert any("vùng thiếu ảnh có thể bị mờ hoặc thủng" in line for line in advice)

    measured["quality"] = PoseQuality(**(base | {"registered_frames": 80, "registered_ratio": 0.8}))
    plain = {metric.key: metric for metric in scorecard._pose_metrics(registry, SimpleNamespace())}  # type: ignore[arg-type]
    assert plain["pose.registered_ratio"].verdict == "ok" and "pose.retry_steps" not in plain
