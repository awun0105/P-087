"""ADR 0001 §2 — đề xuất tỉ lệ/mặt sàn tự động: artifact ESTIMATED và nguồn `ai_estimated` của REC-06."""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from src.services.orchestration.artifacts import ArtifactNotFoundError
from src.services.reconstruction import metric_proposal, publish_json, user_metric_port
from src.services.reconstruction.metric_port import MeasurementDeclaration, UserMetricInput
from src.services.reconstruction.metric_proposal import (
    MetricProposal,
    MogeSettings,
    load_proposal,
    proposal_uri,
    propose_metric,
)
from src.services.reconstruction.rgb.canonical.auto_scale import FrameSamples
from src.services.reconstruction.rgb.canonical.metric import MetricCanonicalizer, MetricDependencies
from tests.test_reconstruction.test_rec06_user_metric_port import JOB, _world

TRUE_SCALE = 2.5


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, noise: float = 0.02):  # noqa: ANN202
    """World fixture REC-03/04 (3 camera thật) + điểm thưa tổng hợp: sàn phẳng dưới camera và một bức tường."""
    port, visual, data, resolver, writer = _world(tmp_path)
    store_root = tmp_path / "store"
    frame_store = resolver.poses.frames

    def resolve(reference):  # noqa: ANN001, ANN202 - như _world: frame set của fixture ở store riêng
        try:
            return resolver.resolve(reference)
        except ArtifactNotFoundError:
            return frame_store._resolve(reference)

    def locate(uri: str) -> Path | None:
        path = store_root / uri.removeprefix("artifact://")
        return path if path.is_file() else None

    poses = resolver.poses.load(visual.artifact.source_camera_poses).poses
    centers = np.array([pose.translation for pose in poses])
    rng = np.random.default_rng(11)
    floor_z = float(centers[:, 2].min()) - 1.0
    samples, truth = [], {}
    for pose in poses:
        floor = np.column_stack([rng.uniform(-3, 3, 120), rng.uniform(-3, 3, 120), np.full(120, floor_z)])
        wall = np.column_stack([np.full(60, 4.0), rng.uniform(-3, 3, 60), rng.uniform(floor_z, floor_z + 2, 60)])
        points = np.vstack([floor, wall])
        depth = rng.uniform(1.0, 8.0, len(points))
        samples.append(
            FrameSamples(
                frame_id=pose.frame_id,
                pixels=rng.uniform(0, 64, (len(points), 2)),
                points=points,
                depth_sfm=depth,
                rotation=np.eye(3),
            )  # fmt: skip
        )
        normals = np.vstack([np.tile([0.0, 0.0, 1.0], (120, 1)), np.tile([-1.0, 0.0, 0.0], (60, 1))])
        truth[pose.frame_id] = (depth * TRUE_SCALE * rng.normal(1.0, noise, len(points)), normals)
    monkeypatch.setattr(metric_proposal, "sparse_samples", lambda *args, **kwargs: samples)
    # Hướng "xuống" của scene tổng hợp là −z (sàn ở z thấp): trục y của mọi camera trỏ về −z.
    monkeypatch.setattr(
        metric_proposal, "rotation_matrix", lambda q: np.array([[1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]])
    )
    calls: list[dict] = []

    def fake_moge(request: dict, workspace: Path, settings: MogeSettings) -> dict[str, np.ndarray]:
        calls.append(request)
        result = {}
        for frame in request["frames"]:
            depth, normals = truth[frame["frame_id"]]
            assert len(frame["pixels"]) == len(depth) and Path(frame["image"]).is_file()
            assert frame["fov_x_degrees"] == pytest.approx(math.degrees(2 * math.atan(640 / 800)))
            result[f"{frame['frame_id']}_depth"] = depth
            result[f"{frame['frame_id']}_normal"] = normals
            result[f"{frame['frame_id']}_valid"] = np.ones(len(depth), dtype=bool)
        return result

    monkeypatch.setattr(metric_proposal, "_run_moge", fake_moge)
    model = tmp_path / "model.pt"
    model.write_bytes(b"weights")
    settings = MogeSettings(python=Path(sys.executable), model=model)
    arguments = (JOB, visual.reference, resolve, writer, locate, tmp_path / "work", settings)
    return arguments, calls, locate, visual, writer, port, data, resolver, store_root


def test_proposal_is_estimated_bound_to_visual_and_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arguments, calls, locate, visual, *_ = _setup(tmp_path, monkeypatch)
    reference = propose_metric(*arguments)
    assert reference is not None and reference.artifact_uri == proposal_uri(JOB, visual.reference)
    assert (
        reference.artifact_type == "MetricScaleProposal"
        and visual.reference.artifact_checksum[7:] in reference.artifact_uri
    )
    proposal = load_proposal(JOB, visual.reference, locate)
    assert proposal is not None and proposal.status == "ESTIMATED"
    assert proposal.scale_m_per_sfm_unit == pytest.approx(TRUE_SCALE, rel=0.02)
    assert proposal.frames_used == 3 and proposal.pairs_used == 3 * 180
    assert proposal.relative_uncertainty == pytest.approx(1.2533 * proposal.frame_dispersion / math.sqrt(3))
    assert proposal.model_checksum.startswith("sha256:")
    # Sàn và hai đoạn nằm trên mặt z = floor_z; khoảng cách = độ dài SfM × tỉ lệ đề xuất.
    assert proposal.floor is not None and proposal.segments is not None
    heights = {round(point[2], 3) for point in proposal.floor.points}
    assert len(heights) == 1 and proposal.floor.support_points >= 300
    segment = proposal.segments
    expected = math.dist(segment.point_a, segment.point_b) * proposal.scale_m_per_sfm_unit
    assert segment.distance_m == pytest.approx(expected) and segment.distance_m > 0.5
    # Gọi lại: trả đúng artifact đã có, không chạy lại mô hình.
    assert propose_metric(*arguments) == reference and len(calls) == 1


def test_no_runtime_no_evidence_or_runtime_error_publish_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments, calls, locate, visual, *_ = _setup(tmp_path, monkeypatch)
    disabled = (*arguments[:-1], MogeSettings(python=None, model=None))
    assert propose_metric(*disabled) is None and not calls  # không bật: không chạy gì
    monkeypatch.setattr(metric_proposal, "align_scale", lambda pairs: None)
    assert propose_metric(*arguments) is None and load_proposal(JOB, visual.reference, locate) is None
    monkeypatch.setattr(metric_proposal, "_run_moge", lambda *args: (_ for _ in ()).throw(ValueError("MoGe lỗi")))
    with pytest.raises(ValueError, match="MoGe lỗi"):
        propose_metric(*arguments)
    assert load_proposal(JOB, visual.reference, locate) is None


def test_proposal_of_another_job_or_visual_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arguments, _, locate, visual, *_ = _setup(tmp_path, monkeypatch)
    propose_metric(*arguments)
    path = locate(proposal_uri(JOB, visual.reference))
    assert path is not None
    forged = MetricProposal.model_validate_json(path.read_bytes()).model_copy(update={"job_id": "job-other"})
    with pytest.raises(ValueError, match="job hoặc bản 3DGS khác"):
        load_proposal(JOB, visual.reference, lambda uri: _written(tmp_path, forged))


def _written(tmp_path: Path, proposal: MetricProposal) -> Path:
    path = tmp_path / "forged.json"
    path.write_text(proposal.model_dump_json())
    return path


def _estimated_input(proposal: MetricProposal) -> UserMetricInput:
    assert proposal.floor is not None and proposal.segments is not None
    segment = proposal.segments
    return UserMetricInput(
        floor_points=proposal.floor.points,
        point_a=segment.point_a,
        point_b=segment.point_b,
        distance_m=segment.distance_m,
        check_a=segment.check_a,
        check_b=segment.check_b,
        check_distance_m=segment.check_distance_m,
        distance_source="ai_estimated",
    )


def test_accepting_the_estimate_confirms_with_recorded_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments, _, locate, visual, writer, _, _, resolver, store_root = _setup(tmp_path, monkeypatch)
    reference = propose_metric(*arguments)
    assert reference is not None
    port = user_metric_port(
        arguments[2], writer, lambda uri: (store_root / uri.removeprefix("artifact://")).is_file(), locate
    )
    proposal = port.auto_proposal(JOB, visual.reference)
    assert proposal is not None
    data = _estimated_input(proposal)
    summary = port.preview(JOB, visual.reference, data)
    assert summary.distance_source == "ai_estimated" and summary.check_passed
    assert summary.scale_m_per_sfm_unit == pytest.approx(proposal.scale_m_per_sfm_unit)
    decision = publish_json(writer, lambda _: False, JOB, "decisions", data, "TestDecision")
    confirmed = port.confirm(JOB, visual.reference, data, summary.preview_checksum, decision, lambda *_: True)
    record = MetricCanonicalizer(MetricDependencies(resolver, writer, lambda *_: True)).require_real(confirmed)
    declaration = MeasurementDeclaration.model_validate_json(
        resolver.require(record.preview.request.anchor.measurement_ref).read_bytes()
    )
    # Bản khai nói rõ khoảng cách đến từ ước lượng nào, không trình bày như số đo ngoài đời.
    assert declaration.input.distance_source == "ai_estimated" and declaration.lidar is None
    assert declaration.estimate is not None
    assert declaration.estimate.proposal_checksum == reference.artifact_checksum
    assert declaration.estimate.relative_uncertainty == pytest.approx(proposal.relative_uncertainty)


def test_estimated_source_cannot_carry_made_up_distances(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arguments, _, locate, visual, writer, plain_port, plain_data, _, store_root = _setup(tmp_path, monkeypatch)
    exists = lambda uri: (store_root / uri.removeprefix("artifact://")).is_file()  # noqa: E731
    port = user_metric_port(arguments[2], writer, exists, locate)
    claimed = plain_data.model_copy(update={"distance_source": "ai_estimated"})
    with pytest.raises(ValueError, match="không có đề xuất"):
        port.preview(JOB, visual.reference, claimed)  # chưa có đề xuất nào
    with pytest.raises(ValueError, match="không có đề xuất"):
        plain_port.preview(JOB, visual.reference, claimed)  # deployment không có locate
    propose_metric(*arguments)
    proposal = port.auto_proposal(JOB, visual.reference)
    assert proposal is not None
    data = _estimated_input(proposal)
    for field in ("distance_m", "check_distance_m"):
        with pytest.raises(ValueError, match="không khớp đề xuất"):
            port.preview(JOB, visual.reference, data.model_copy(update={field: getattr(data, field) * 1.05}))
    # Người dùng tự chọn điểm khác vẫn dùng được ước lượng, miễn khoảng cách = độ dài × tỉ lệ đề xuất.
    scale = proposal.scale_m_per_sfm_unit
    moved = data.model_copy(update={"point_b": (data.point_b[0] + 0.5, data.point_b[1], data.point_b[2])})
    moved = moved.model_copy(update={"distance_m": math.dist(moved.point_a, moved.point_b) * scale})
    assert port.preview(JOB, visual.reference, moved).distance_source == "ai_estimated"
    # Số đo thật cho cùng điểm vẫn đi đường cũ, không cần đề xuất.
    measured = data.model_copy(update={"distance_source": "user_measured"})
    assert plain_port.preview(JOB, visual.reference, measured).distance_source == "user_measured"


def test_runner_process_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ranh giới subprocess: request JSON vào, npz ra; exit khác 0 và quá giờ thành lỗi có ngữ cảnh."""
    script = tmp_path / "fake_runner.py"
    script.write_text(
        "import argparse, json, sys\n"
        "import numpy as np\n"
        "p = argparse.ArgumentParser(); p.add_argument('--request'); p.add_argument('--result'); a = p.parse_args()\n"
        "r = json.load(open(a.request))\n"
        "if r['model'] == 'fail': sys.exit(3)\n"
        "if r['model'] == 'slow':\n    import time; time.sleep(30)\n"
        "np.savez(a.result, **{f\"{f['frame_id']}_depth\": np.ones(len(f['pixels'])) for f in r['frames']})\n"
    )
    monkeypatch.setattr(metric_proposal, "RUNNER", script)
    settings = MogeSettings(python=Path(sys.executable), model=tmp_path / "m.pt", timeout_seconds=20)
    request = {"model": "ok", "frames": [{"frame_id": 7, "pixels": [[1, 2], [3, 4]]}]}
    result = metric_proposal._run_moge(request, tmp_path / "w", settings)
    assert result["7_depth"].tolist() == [1.0, 1.0]
    assert json.loads((tmp_path / "w" / "moge.request.json").read_text()) == request
    with pytest.raises(ValueError, match="exit 3"):
        metric_proposal._run_moge({**request, "model": "fail"}, tmp_path / "w2", settings)
    with pytest.raises(ValueError, match="quá thời gian"):
        metric_proposal._run_moge(
            {**request, "model": "slow"}, tmp_path / "w3", settings.model_copy(update={"timeout_seconds": 0.5})
        )
    with pytest.raises(ValueError, match="Không chạy được"):
        metric_proposal._run_moge(
            request, tmp_path / "w4", settings.model_copy(update={"python": tmp_path / "missing-python"})
        )


def test_segments_that_rec06_would_reject_are_not_offered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Đoạn kiểm quá ngắn so với ngưỡng của bước xem trước: giữ tỉ lệ và sàn, không điền sẵn hai đoạn."""
    arguments, _, locate, visual, writer, _, _, _, store_root = _setup(tmp_path, monkeypatch)
    propose_metric(*arguments)
    path = locate(proposal_uri(JOB, visual.reference))
    assert path is not None
    stored = MetricProposal.model_validate_json(path.read_bytes())
    assert stored.segments is not None
    short = stored.model_copy(update={"segments": stored.segments.model_copy(update={"check_distance_m": 0.52})})
    port = user_metric_port(arguments[2], writer, lambda uri: False, lambda uri: _written(tmp_path, short))
    offered = port.auto_proposal(JOB, visual.reference)
    assert offered is not None and offered.segments is None and offered.floor == short.floor
    assert offered.scale_m_per_sfm_unit == short.scale_m_per_sfm_unit
