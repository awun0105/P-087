"""Xuất job thành bundle trong thư viện mẫu: nguyên tử, không ghi đè, dọn thư mục tạm, gắn asset từng bước."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.models.contracts.manifests import StageId
from src.services.orchestration.artifacts import ArtifactStoreError, sha256_file
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.samples import DemoLibrary, DemoSource
from src.services.orchestration.samples.export import (
    AlreadyPublishedError,
    SampleExportError,
    StageAssetSpec,
    export_job_bundle,
    load_stage_assets,
    publish_job_bundle,
    published_sample_id,
    slugify,
)

JOB_ID = "job-fixture-001"
SOURCE = DemoSource(dataset="Studio", sequence="Kho thử")


class _Resolver:
    def __init__(self, splat: Path, display_video: Path | None = None) -> None:
        self.splat = splat
        self.display_video = display_video

    def require_uri(self, uri: str, checksum: str) -> Path:
        raise ArtifactStoreError("không có artifact này")

    def require(self, reference: object) -> Path:
        if reference == "DELIVERY":
            return self.splat
        if reference == "RAW_VIDEO_MANIFEST":
            raise AssertionError("video gốc chưa che không được đọc để đưa vào thư viện công khai")
        if getattr(reference, "artifact_type", None) == "DISPLAY_VIDEO" and self.display_video is not None:
            return self.display_video
        raise ArtifactStoreError("không có artifact này")


def _registry(tmp_path: Path, *, preview_ok: bool = True, raw_video: bool = False, display_video: bool = False):  # noqa: ANN202
    real = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    real.seed_from_fixtures()
    splat = tmp_path / "preview.sog"
    splat.write_bytes(b"sog-bytes" * 20)
    display = tmp_path / "display.mp4"
    display.write_bytes(b"replay-video")
    preview = SimpleNamespace(
        delivery_ref="DELIVERY", camera_pose_ref=None, attempt_id="attempt-1", producer_version="v1"
    )

    def get_preview(job_id: str):  # noqa: ANN202
        if not preview_ok:
            raise ArtifactStoreError("chưa có preview")
        return preview

    return SimpleNamespace(
        get_job=real.get_job,
        scene=real.scene,
        persistence=None,
        get_preview=get_preview,
        runtime_resolver=_Resolver(splat, display if display_video else None),
        get_project=lambda project_id: SimpleNamespace(
            input_manifest_ref="RAW_VIDEO_MANIFEST" if raw_video else ("IMAGE_MANIFEST" if display_video else None),
            input_video=None,
            display_video_ref=(
                SimpleNamespace(artifact_type="DISPLAY_VIDEO", artifact_checksum=sha256_file(display))
                if display_video
                else None
            ),
        ),
        list_job_attempts=lambda job_id: [],
    ), splat


def test_dataset_sample_exports_replay_video_without_reading_it_as_input(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path, display_video=True)
    out = tmp_path / "sample"
    manifest = export_job_bundle(
        registry, JOB_ID, out, demo_id="dataset-video", title="Dataset", description="", source=SOURCE
    )
    assert manifest.video is not None and manifest.video.name == "display.mp4"
    assert manifest.video_caption == "Video ghép từ ảnh gốc, chỉ để xem lại"
    assert (out / "files" / manifest.video.name).read_bytes() == b"replay-video"


def test_slugify_drops_vietnamese_marks() -> None:
    assert slugify("Kho thử Đường đi!") == "kho-thu-duong-di"
    assert slugify("???") == ""


def test_publish_writes_a_valid_bundle_atomically(tmp_path: Path) -> None:
    registry, splat = _registry(tmp_path)
    library = tmp_path / "library"
    manifest = publish_job_bundle(
        registry, JOB_ID, library, title="Kho thử Đường đi", description="Mô tả", source=SOURCE
    )
    assert manifest.demo_id.startswith("kho-thu-duong-di-")
    assert manifest.provenance["job_id"] == JOB_ID
    assert manifest.splat.checksum == sha256_file(splat)
    # Thư viện đọc được ngay và không còn thư mục tạm.
    assert [child.name for child in library.iterdir()] == [manifest.demo_id]
    summaries = DemoLibrary(library).summaries()
    assert [item.sample_id for item in summaries] == [manifest.demo_id]
    assert published_sample_id(library, JOB_ID) == manifest.demo_id
    assert len(manifest.stages) == 8 and manifest.stages[0].stage_id == StageId.INPUT_VALIDATE


def test_export_preserves_preview_orientation_without_changing_splat_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import math

    from src.services.orchestration.samples import export as module

    registry, splat = _registry(tmp_path)
    rotation = (-math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5))
    monkeypatch.setattr(module, "preview_display_rotation", lambda *_: rotation)
    out = tmp_path / "aligned"
    manifest = export_job_bundle(registry, JOB_ID, out, demo_id="aligned", title="Kho", description="", source=SOURCE)
    reloaded = DemoLibrary(out).bundle("aligned").manifest()
    assert reloaded.display_rotation_xyzw == manifest.display_rotation_xyzw == rotation
    assert (out / "files" / manifest.splat.name).read_bytes() == splat.read_bytes()


def test_publishing_twice_returns_the_existing_sample_and_never_overwrites(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    library = tmp_path / "library"
    first = publish_job_bundle(registry, JOB_ID, library, title="Kho A", description="", source=SOURCE)
    before = (library / first.demo_id / "manifest.json").read_bytes()
    with pytest.raises(AlreadyPublishedError) as error:
        publish_job_bundle(registry, JOB_ID, library, title="Tên khác", description="", source=SOURCE)
    assert error.value.demo_id == first.demo_id
    assert (library / first.demo_id / "manifest.json").read_bytes() == before
    assert [child.name for child in library.iterdir()] == [first.demo_id]


def test_failed_export_leaves_no_partial_directory(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path, preview_ok=False)
    library = tmp_path / "library"
    with pytest.raises(SampleExportError, match="bản xem 3DGS"):
        publish_job_bundle(registry, JOB_ID, library, title="Kho A", description="", source=SOURCE)
    assert list(library.iterdir()) == []


def test_stage_assets_are_copied_with_flat_names_and_listed(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    image = tmp_path / "metric.png"
    image.write_bytes(b"png-bytes")
    out = tmp_path / "bundle"
    manifest = export_job_bundle(
        registry,
        JOB_ID,
        out,
        demo_id="with-assets",
        title="Có asset",
        description="",
        source=SOURCE,
        stage_assets={
            StageId.METRIC_CANONICALIZE: [
                StageAssetSpec(kind="image", title="Điểm đo", path=image),
                StageAssetSpec(kind="facts", facts=(("Khoảng cách A–B", "1.20 m"),)),
            ]
        },
    )
    metric = next(stage for stage in manifest.stages if stage.stage_id == StageId.METRIC_CANONICALIZE)
    assert [asset.kind for asset in metric.assets] == ["image", "facts"]
    assert metric.assets[0].file is not None and (out / "files" / metric.assets[0].file.name).is_file()
    assert metric.assets[0].file in manifest.files()


def test_asset_for_an_unknown_stage_or_missing_file_is_refused(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    with pytest.raises(SampleExportError, match="thiếu file"):
        export_job_bundle(
            registry,
            JOB_ID,
            tmp_path / "b1",
            demo_id="x",
            title="x",
            description="",
            source=SOURCE,
            stage_assets={StageId.METRIC_CANONICALIZE: [StageAssetSpec(kind="image", path=tmp_path / "missing.png")]},
        )
    with pytest.raises(SampleExportError, match="không có bước"):
        export_job_bundle(
            registry,
            JOB_ID,
            tmp_path / "b2",
            demo_id="x",
            title="x",
            description="",
            source=SOURCE,
            stage_assets={StageId.LIDAR_INGEST: [StageAssetSpec(kind="facts", facts=(("a", "b"),))]},
        )


def test_assets_json_is_read_relative_to_the_file(tmp_path: Path) -> None:
    (tmp_path / "assets.json").write_text(
        '{"ST-RGB-GEOMETRY": [{"kind": "image", "title": "Lưới", "path": "mesh.png"},'
        ' {"kind": "facts", "facts": [{"label": "Voxel", "value": "5 cm"}]}]}',
        encoding="utf-8",
    )
    specs = load_stage_assets(tmp_path / "assets.json")
    items = specs[StageId.RGB_GEOMETRY]
    assert items[0].path == tmp_path / "mesh.png" and items[1].facts == (("Voxel", "5 cm"),)


def test_export_refuses_a_non_empty_target(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "old.txt").write_text("cũ")
    with pytest.raises(SampleExportError, match="không ghi đè"):
        export_job_bundle(registry, JOB_ID, out, demo_id="x", title="x", description="", source=SOURCE)


def test_more_than_eight_cards_on_a_stage_are_refused_before_any_file_is_written(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    specs = [StageAssetSpec(kind="image", path=image)] * 9
    out = tmp_path / "bundle"
    with pytest.raises(SampleExportError, match="tối đa 8"):
        export_job_bundle(
            registry,
            JOB_ID,
            out,
            demo_id="x",
            title="x",
            description="",
            source=SOURCE,
            stage_assets={StageId.METRIC_CANONICALIZE: specs},
        )
    assert not (out / "files").exists() and not (out / "manifest.json").exists()


def test_a_kind_that_does_not_match_the_file_type_is_refused(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    with pytest.raises(SampleExportError, match="thiếu file hợp lệ"):
        export_job_bundle(
            registry,
            JOB_ID,
            tmp_path / "b",
            demo_id="x",
            title="x",
            description="",
            source=SOURCE,
            stage_assets={StageId.METRIC_CANONICALIZE: [StageAssetSpec(kind="video", path=image)]},
        )


def test_a_failure_after_files_were_copied_cleans_up_so_the_run_can_be_retried(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    out = tmp_path / "bundle"
    # Tiêu đề rỗng làm DemoManifest không hợp lệ sau khi splat đã được copy.
    with pytest.raises(SampleExportError, match="không hợp lệ"):
        export_job_bundle(registry, JOB_ID, out, demo_id="x", title="", description="", source=SOURCE)
    assert not (out / "files").exists()
    ok = export_job_bundle(registry, JOB_ID, out, demo_id="x", title="Tên", description="", source=SOURCE)
    assert ok.title == "Tên"


def test_frame_count_beyond_the_manifest_limit_is_refused(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    with pytest.raises(SampleExportError, match="từ 2 đến 48"):
        export_job_bundle(
            registry, JOB_ID, tmp_path / "b", demo_id="x", title="x", description="", source=SOURCE, frames=49
        )


def test_invalid_assets_json_is_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "assets.json"
    path.write_text('{"ST-NOT-A-STAGE": []}', encoding="utf-8")
    with pytest.raises(SampleExportError, match="assets.json"):
        load_stage_assets(path)
    path.write_text('{"ST-RGB-GEOMETRY": [{"title": "thiếu kind"}]}', encoding="utf-8")
    with pytest.raises(SampleExportError, match="assets.json"):
        load_stage_assets(path)


def test_a_lock_held_by_another_publisher_blocks_a_second_publish(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    library = tmp_path / "library"
    (library / f".publishing-{JOB_ID}").mkdir(parents=True)
    with pytest.raises(SampleExportError, match="đang được xuất"):
        publish_job_bundle(registry, JOB_ID, library, title="Kho", description="", source=SOURCE)
    assert [child.name for child in library.iterdir()] == [f".publishing-{JOB_ID}"]


def test_a_lidar_job_keeps_its_lidar_stages_when_exported(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from src.models.contracts.manifests import StageArtifact, StageStatus
    from src.services.orchestration.samples.export import stage_durations

    registry, _ = _registry(tmp_path)
    job = registry.get_job(JOB_ID)
    when = datetime(2026, 10, 10, tzinfo=UTC)
    ingest = StageArtifact(
        stage_id=StageId.LIDAR_INGEST,
        status=StageStatus.SUCCEEDED,
        artifact_type="LidarIngest",
        artifact_uri="artifact://jobs/j/lidar",
        artifact_checksum="sha256:" + "a" * 64,
        data_class="derived",
        started_at=when,
        completed_at=when,
    )
    stages = stage_durations(job.model_copy(update={"stage_artifacts": [ingest]}), [])
    ids = [stage.stage_id for stage in stages]
    assert StageId.LIDAR_INGEST in ids and ids.index(StageId.LIDAR_INGEST) == ids.index(StageId.FRAME_EXTRACT) + 1
    assert StageId.LIDAR_ODOMETRY not in ids
    # Job không LiDAR thì pipeline giữ nguyên 8 bước.
    assert len(stage_durations(job, [])) == 8


def test_a_failed_export_never_touches_an_existing_bundle(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    out = tmp_path / "published"
    (out / "files").mkdir(parents=True)
    (out / "files" / "scene.sog").write_bytes(b"da-xuat-ban")
    (out / "manifest.json").write_text("{}")
    with pytest.raises(SampleExportError, match="không ghi đè"):
        export_job_bundle(registry, JOB_ID, out, demo_id="x", title="x", description="", source=SOURCE)
    # Lỗi xảy ra trước khi lần chạy này tạo bất cứ thứ gì: các lỗi khác (frame, preview) cũng không được xoá bundle cũ.
    with pytest.raises(SampleExportError):
        export_job_bundle(registry, JOB_ID, out, demo_id="x", title="x", description="", source=SOURCE, frames=1)
    assert (out / "files" / "scene.sog").read_bytes() == b"da-xuat-ban" and (out / "manifest.json").read_text() == "{}"


def test_the_raw_video_is_not_published_when_the_job_masked_faces_and_plates(tmp_path: Path, monkeypatch) -> None:
    from src.services.orchestration.samples import export as export_module

    registry, _ = _registry(tmp_path, raw_video=True)
    monkeypatch.setattr(export_module, "sanitized_frame_stage", lambda job: object())
    manifest = export_job_bundle(
        registry, JOB_ID, tmp_path / "masked", demo_id="x", title="Đã che", description="", source=SOURCE
    )
    assert manifest.video is None
    # Không che thì vẫn cố đọc video gốc (resolver giả báo lỗi để chứng minh đường đó được đi).
    monkeypatch.setattr(export_module, "sanitized_frame_stage", lambda job: None)
    with pytest.raises(AssertionError, match="video gốc"):
        export_job_bundle(registry, JOB_ID, tmp_path / "plain", demo_id="y", title="Gốc", description="", source=SOURCE)


def test_removed_job_can_be_published_again_without_overwriting_the_old_bundle(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    root = tmp_path / "library"
    first = publish_job_bundle(registry, JOB_ID, root, title="Kho", description="", source=SOURCE)
    original = (root / first.demo_id / "manifest.json").read_bytes()
    DemoLibrary(root).unpublish(first.demo_id)
    assert published_sample_id(root, JOB_ID) is None
    second = publish_job_bundle(registry, JOB_ID, root, title="Kho", description="Mới", source=SOURCE)
    assert second.demo_id != first.demo_id
    assert published_sample_id(root, JOB_ID) == second.demo_id
    assert (root / first.demo_id / "manifest.json").read_bytes() == original


def test_sample_optional_object_geometry_is_validated(tmp_path: Path) -> None:
    from pydantic import ValidationError

    from src.services.orchestration.samples.models import DemoManifest, DemoObjectGeometry

    registry, _ = _registry(tmp_path)
    demo = export_job_bundle(
        registry, JOB_ID, tmp_path / "bundle", demo_id="x", title="x", description="", source=SOURCE
    )
    assert DemoManifest.model_validate_json(demo.model_dump_json()).object_geometry is None
    demo.object_geometry = DemoObjectGeometry(state="succeeded", objectgs_count=2, shell_count=3, collider_count=5)
    assert DemoManifest.model_validate_json(demo.model_dump_json()).object_geometry.collider_count == 5
    with pytest.raises(ValidationError):
        DemoObjectGeometry(state="succeeded", objectgs_count=-1)


@pytest.mark.parametrize("source", ["user_measured", "ai_estimated", "lidar_trajectory"])
@pytest.mark.parametrize("objectgs", [False, True])
@pytest.mark.parametrize("request_status", ["done", "failed", "stale"])
def test_sample_exports_recorded_metric_collision_objects_and_geometry(
    tmp_path: Path, source: str, objectgs: bool, request_status: str
) -> None:
    import json
    from contextlib import contextmanager
    from datetime import UTC, datetime

    from src.models.contracts.artifacts import ArtifactDataClass, ProductArtifactRef
    from src.models.contracts.manifests import StageArtifact, StageStatus

    registry, _ = _registry(tmp_path)
    refs = {}

    def publish(name, payload):  # noqa: ANN001, ANN202
        path = tmp_path / name
        path.write_text(json.dumps(payload))
        ref = ProductArtifactRef(
            artifact_type="Evidence",
            schema_version="1.0",
            artifact_uri=f"artifact://jobs/{JOB_ID}/{name}",
            artifact_checksum=sha256_file(path),
            data_class=ArtifactDataClass.DERIVED,
            producer_stage=StageId.METRIC_CANONICALIZE,
            job_id=JOB_ID,
        )
        refs[ref.artifact_uri] = path
        return ref

    declaration = publish(
        "declaration.json",
        {
            "job_id": JOB_ID,
            "input": {"distance_source": source, "check_a": [0, 0, 0], "check_b": [1, 0, 0], "check_distance_m": 2},
            "estimate": {
                "method": "lidar_trajectory_alignment"
                if source == "lidar_trajectory"
                else "moge2_sparse_depth_scale_only"
            },
        },
    )
    confirmation = publish(
        "confirmation.json",
        {
            "preview": {
                "transform": {"scale_m_per_sfm_unit": 2},
                "request": {"anchor": {"measurement_ref": declaration.model_dump(mode="json")}},
            }
        },
    )
    import trimesh

    mesh_path = tmp_path / "collision.glb"
    mesh_path.write_bytes(trimesh.creation.box().export(file_type="glb"))
    geometry_ref = {
        "artifact_type": "LidarCollisionCandidate" if source == "lidar_trajectory" else "GeometryArtifact",
        "artifact_uri": f"artifact://jobs/{JOB_ID}/collision.glb",
        "artifact_checksum": sha256_file(mesh_path),
    }
    refs[geometry_ref["artifact_uri"]] = mesh_path
    bundle = publish(
        "bundle.json",
        {
            "canonical_geometry_ref": geometry_ref,
            "rgb_geometry_ref": None if source == "lidar_trajectory" else geometry_ref,
        },
    )
    scene = publish(
        "scene.json",
        {
            "scene_revision": "rev-002",
            "provenance": {"object_geometry": "awaiting_review" if request_status == "failed" else "ready"},
            "environment": {},
            "objects": [
                {
                    "origin": "reconstructed",
                    "collider": {},
                    "provenance": {"surface_selection": {"chosen": "objectgs" if objectgs else "gaussian_shell"}},
                },
                {"origin": "user_added", "collider": {}, "provenance": {}},
            ],
        },
    )
    registry.runtime_resolver.require_uri = lambda uri, checksum: refs[uri]
    registry.scene.head_repository = SimpleNamespace(get=lambda job_id: SimpleNamespace(scene_reference=scene))

    @contextmanager
    def transaction():  # noqa: ANN202
        payload = {
            "mode": "geometry",
            "status": request_status if request_status != "stale" else "done",
            "result_revision": "rev-001" if request_status == "stale" else "rev-002",
            "base_revision": "rev-002",
            "started_at": "2026-10-17T00:00:00Z",
            "finished_at": "2026-10-17T00:00:12Z",
        }
        yield SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchone=lambda: (json.dumps(payload),)))

    registry.persistence = SimpleNamespace(database=SimpleNamespace(transaction=transaction))
    job = registry.get_job(JOB_ID)
    records = [
        StageArtifact(
            stage_id=stage_id,
            status=StageStatus.SUCCEEDED,
            artifact_type=kind,
            artifact_uri=ref.artifact_uri,
            artifact_checksum=ref.artifact_checksum,
            data_class=ArtifactDataClass.DERIVED,
            completed_at=datetime.now(UTC),
        )
        for stage_id, kind, ref in [
            (StageId.METRIC_CANONICALIZE, "RGBMetricConfirmation", confirmation),
            (StageId.METRIC_CANONICALIZE, "ReconstructionBundle", bundle),
            (StageId.RGB_GEOMETRY, "GeometryArtifact", bundle),
            (StageId.OBJECT_EXTRACT, "SceneIR", scene),
        ]
    ]
    registry.get_job = lambda job_id: job.model_copy(update={"stage_artifacts": records})
    demo = export_job_bundle(
        registry, JOB_ID, tmp_path / "export", demo_id="x", title="x", description="", source=SOURCE
    )
    facts = {
        stage.stage_id: {fact.label: fact.value for asset in stage.assets for fact in asset.facts}
        for stage in demo.stages
    }
    assert facts[StageId.METRIC_CANONICALIZE]["Tỉ lệ"] == "2 m/đơn vị"
    assert facts[StageId.METRIC_CANONICALIZE]["Sai số C–D"] == "0 m"
    assert facts[StageId.RGB_GEOMETRY]["Nguồn lưới va chạm"] == ("LiDAR" if source == "lidar_trajectory" else "ảnh")
    assert facts[StageId.RGB_GEOMETRY]["Số tam giác của lưới"] == "12"
    assert facts[StageId.OBJECT_EXTRACT]["Số vật ứng viên"] == "1"
    assert demo.object_geometry.objectgs_count == int(objectgs)
    assert demo.object_geometry.shell_count == int(not objectgs)
    assert demo.object_geometry.collider_count == 1
    assert demo.object_geometry.duration_seconds == (12 if request_status == "done" else None)
    assert demo.object_geometry.state == ("failed" if request_status == "failed" else "succeeded")


def test_sample_prepare_timings_are_grouped_instead_of_fake_zero(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from src.models.contracts.manifests import JobStatus, StageArtifact, StageStatus
    from src.services.orchestration.samples.export import stage_durations

    registry, _ = _registry(tmp_path)
    job = registry.get_job(JOB_ID)
    start = datetime(2026, 10, 17, tzinfo=UTC)
    records = [
        StageArtifact(
            stage_id=stage_id,
            status=StageStatus.SUCCEEDED,
            artifact_type="Evidence",
            artifact_uri=f"artifact://jobs/{JOB_ID}/{stage_id.value}",
            artifact_checksum="sha256:" + "a" * 64,
            data_class="derived",
            completed_at=start + timedelta(seconds=12),
        )
        for stage_id in [StageId.INPUT_VALIDATE, StageId.PRIVACY_GATE, StageId.FRAME_EXTRACT]
    ]
    event = SimpleNamespace(
        attempt=1, status=JobStatus.RUNNING, current_stage=StageId.INPUT_VALIDATE, recorded_at=start
    )
    stages = stage_durations(job.model_copy(update={"stage_artifacts": records}), [event])
    assert [stage.duration_seconds for stage in stages[:3]] == [12, None, None]
    assert "gộp chung 3 bước" in stages[0].summary
    assert all(stage.duration_seconds != 0 for stage in stages)
    stages = stage_durations(job.model_copy(update={"stage_artifacts": records}), [])
    assert all(stage.duration_seconds is None for stage in stages[:3])
