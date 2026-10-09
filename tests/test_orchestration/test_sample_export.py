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
    def __init__(self, splat: Path) -> None:
        self.splat = splat

    def require(self, reference: object) -> Path:
        if reference == "DELIVERY":
            return self.splat
        raise ArtifactStoreError("không có artifact này")


def _registry(tmp_path: Path, *, preview_ok: bool = True):  # noqa: ANN202
    real = ProjectRegistry(runtime_root=tmp_path / "artifacts")
    real.seed_from_fixtures()
    splat = tmp_path / "preview.sog"
    splat.write_bytes(b"sog-bytes" * 20)
    preview = SimpleNamespace(
        delivery_ref="DELIVERY", camera_pose_ref=None, attempt_id="attempt-1", producer_version="v1"
    )

    def get_preview(job_id: str):  # noqa: ANN202
        if not preview_ok:
            raise ArtifactStoreError("chưa có preview")
        return preview

    return SimpleNamespace(
        get_job=real.get_job,
        get_preview=get_preview,
        runtime_resolver=_Resolver(splat),
        get_project=lambda project_id: SimpleNamespace(input_manifest_ref=None),
        list_job_attempts=lambda job_id: [],
    ), splat


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
