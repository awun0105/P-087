"""Xuất một job đã chạy thật thành demo bundle trong thư viện mẫu.

Dùng chung cho CLI (`scripts/demo/export_demo_bundle.py`) và nút "Đặt làm bản demo" của Reviewer. Bundle chỉ chứa output
thật của job (video gốc, frame đại diện, SOG preview, thời lượng từ journal) và các asset hiển thị do người xuất cung
cấp; không có số liệu nào do UI tự điền. Không bao giờ ghi đè bundle cũ.
"""

import json
import logging
import re
import shutil
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from src.models.contracts.manifests import InputManifest, JobManifest, JobStatus, StageId, StageStatus
from src.services.orchestration.artifacts import ArtifactStoreError, sha256_file
from src.services.orchestration.jobs.dispatch import prepared_frame_reference
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.jobs.progress import MVP_PIPELINE, sanitized_frame_stage
from src.services.orchestration.jobs.stage_results import recorded_results, result_facts
from src.services.orchestration.jobs.stage_views import preview_display_rotation
from src.services.orchestration.samples.bundle import UNPUBLISHED_MARKER, DemoLibrary, DemoUnavailableError
from src.services.orchestration.samples.models import (
    DemoFact,
    DemoFile,
    DemoManifest,
    DemoObjectGeometry,
    DemoSource,
    DemoStage,
    DemoStageAsset,
    pipeline_for_stage_ids,
)
from src.services.reconstruction import camera_markers

if TYPE_CHECKING:
    from src.services.orchestration.projects.registry import ProjectRegistry

logger = logging.getLogger(__name__)
_MEDIA = {".mp4": "video/mp4", ".mov": "video/quicktime", ".png": "image/png", ".jpg": "image/jpeg"}
_MEDIA.update({".jpeg": "image/jpeg", ".sog": "application/octet-stream", ".ply": "application/octet-stream"})
_ASSET_SUFFIXES = {"image": {".png", ".jpg", ".jpeg"}, "video": {".mp4", ".mov"}}
#: Giới hạn của manifest (xem `DemoStage.assets`, `DemoManifest.frames`); kiểm trước khi copy file.
MAX_ASSETS_PER_STAGE = 8
MAX_FRAMES = 48


class SampleExportError(ValueError):
    """Job chưa xuất được thành bundle (thiếu preview, sai checksum, thư mục đích đã có dữ liệu…)."""


class AlreadyPublishedError(SampleExportError):
    """Job này đã nằm trong thư viện mẫu; `demo_id` là mẫu đang có."""

    def __init__(self, demo_id: str) -> None:
        super().__init__(f"Job này đã có trong thư viện mẫu ({demo_id})")
        self.demo_id = demo_id


@dataclass(frozen=True)
class StageAssetSpec:
    """Asset do người xuất khai báo; `path` là file nguồn (copy vào bundle) với kind `image`/`video`."""

    kind: str
    title: str = ""
    caption: str = ""
    path: Path | None = None
    facts: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def load_stage_assets(path: Path) -> dict[StageId, list[StageAssetSpec]]:
    """Đọc `assets.json`: `{"ST-METRIC-CANONICALIZE": [{"kind": "image", "path": "metric.png", ...}, ...]}`.

    `path` của asset tính từ thư mục chứa file JSON. Sai kind/thiếu file được báo ngay khi dựng bundle.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        specs: dict[StageId, list[StageAssetSpec]] = {}
        for stage_key, items in raw.items():
            stage_id = StageId(stage_key)
            specs[stage_id] = [
                StageAssetSpec(
                    kind=item["kind"],
                    title=item.get("title", ""),
                    caption=item.get("caption", ""),
                    path=(path.parent / item["path"]) if item.get("path") else None,
                    facts=tuple((fact["label"], fact["value"]) for fact in item.get("facts", [])),
                )
                for item in items
            ]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise SampleExportError(f"assets.json không hợp lệ: {error}") from error
    return specs


def stage_durations(job: JobManifest, attempts: Sequence[JobAttemptRecord]) -> list[DemoStage]:
    """Thời lượng thật từng stage: chuỗi completed_at, mốc đầu là lúc attempt RUNNING.

    Stage không có mốc hoàn tất (hoặc mốc lệch) để null thay vì đoán.
    """
    latest = attempts[-1].attempt if attempts else 1
    running = [event for event in attempts if event.attempt == latest and event.status == JobStatus.RUNNING]
    cursor = running[0].recorded_at if running else None
    records = {stage.stage_id: stage for stage in job.stage_artifacts}
    # Gồm cả bước LiDAR mà job thật sự có, để bundle (và phát lại) hiện đủ bước như scene thật.
    present = {*records, *([job.current_stage] if job.current_stage is not None else [])}
    stages = []
    for stage_id in pipeline_for_stage_ids(present):
        record = records.get(stage_id)
        state = (
            "succeeded"
            if record and record.status == StageStatus.SUCCEEDED
            else ("failed" if record and record.status == StageStatus.FAILED else "pending")
        )
        end = record.completed_at if record and state == "succeeded" else None
        start = record.started_at if record else None
        if start is None and stage_id in MVP_PIPELINE:
            start = cursor  # Compatibility: preview cũ chỉ có chuỗi completed_at.
        if stage_id not in MVP_PIPELINE and start is None:
            start = next((event.recorded_at for event in running if event.current_stage == stage_id), None)
        duration = (end - start).total_seconds() if end is not None and start is not None else None
        stages.append(
            DemoStage(
                stage_id=stage_id,
                state=state,
                duration_seconds=duration if duration is not None and duration > 0 else None,
                summary="Mẫu này chưa ghi kết quả của bước này." if state == "pending" else "",
            )
        )
        cursor = end  # Gap thiếu evidence không được gán thời gian của nhiều bước vào stage sau.
    prepare_ids = MVP_PIPELINE[:3]
    prepare = [records.get(stage_id) for stage_id in prepare_ids]
    if any(record is not None and record.started_at is None for record in prepare):
        # Prepare publish ba receipt cùng lúc: chỉ có thể đo thời gian chung.
        for stage in stages[:3]:
            stage.duration_seconds = None
        ends = [record.completed_at for record in prepare if record is not None and record.completed_at is not None]
        if running and running[0].current_stage in prepare_ids and len(ends) == 3:
            elapsed = (max(ends) - running[0].recorded_at).total_seconds()
            if elapsed > 0:
                stages[0].duration_seconds = elapsed
                stages[
                    0
                ].summary = "Thời gian chuẩn bị gộp chung 3 bước: kiểm tra video, quyền riêng tư và tách khung hình."
    return stages


def add_file(out: Path, source: Path, name: str) -> DemoFile:
    """Copy một file vào `files/` của bundle và trả bản ghi allow-list (size + checksum)."""
    target = out / "files" / name
    shutil.copyfile(source, target)
    return DemoFile(
        name=name,
        media_type=_MEDIA.get(target.suffix.lower(), "application/octet-stream"),
        size_bytes=target.stat().st_size,
        checksum=sha256_file(target),
    )


def evenly(items: Sequence[Path], count: int) -> list[Path]:
    """`count` phần tử rải đều (gồm đầu và cuối)."""
    if len(items) <= count:
        return list(items)
    step = (len(items) - 1) / (count - 1)
    return [items[round(i * step)] for i in range(count)]


def prepare_out(out: Path) -> None:
    """Thư mục đích phải trống: không ghi đè bundle cũ."""
    if out.exists() and any(out.iterdir()):
        raise SampleExportError(f"{out} đã có dữ liệu; chọn thư mục mới (không ghi đè bundle cũ)")
    (out / "files").mkdir(parents=True, exist_ok=True)


def write_manifest(out: Path, manifest: DemoManifest) -> None:
    (out / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _job_processing(resolver: object, job: JobManifest) -> dict[str, int | float | str] | None:
    """Thông số thật của job từ `config/processing.json`; job legacy không có → None."""
    from src.services.orchestration.processing import JobProcessingConfig, job_config_reference

    try:
        path = resolver.require(job_config_reference(job.job_id, job.config_checksum))  # type: ignore[attr-defined]
    except ArtifactStoreError:
        return None
    return JobProcessingConfig.model_validate_json(path.read_bytes()).params


def _machine() -> dict[str, str]:
    """GPU/driver đã xử lý, đọc từ RuntimeManifest của worker (không đo lại)."""
    from src.config import get_settings
    from src.models.contracts.manifests import RuntimeManifest

    path = get_settings().product_runtime_manifest
    if path is None or not path.is_file():
        return {}
    manifest = RuntimeManifest.model_validate_json(path.read_bytes())
    keys = ("gpu_model", "vram", "nvidia_driver", "brush", "colmap")
    return {
        key: manifest.components[key].version or ""
        for key in keys
        if key in manifest.components and manifest.components[key].version
    }


def _attach_assets(out: Path, stages: list[DemoStage], specs: Mapping[StageId, Sequence[StageAssetSpec]]) -> None:
    """Gắn asset do người xuất khai báo vào đúng bước; file được copy vào bundle với tên phẳng không trùng."""
    by_id = {stage.stage_id: stage for stage in stages}
    for stage_id, items in specs.items():
        stage = by_id.get(stage_id)
        if stage is None:
            raise SampleExportError(f"Bundle không có bước {stage_id.value} để gắn asset")
        if len(items) > MAX_ASSETS_PER_STAGE:
            raise SampleExportError(f"Bước {stage_id.value} có {len(items)} thẻ; tối đa {MAX_ASSETS_PER_STAGE}")
        for index, spec in enumerate(items, start=1):
            if spec.kind not in {"image", "video", "facts"}:
                raise SampleExportError(f"Loại thẻ không hỗ trợ: {spec.kind}")
            if spec.kind == "facts":
                facts = [DemoFact(label=label, value=value) for label, value in spec.facts]
                stage.assets.append(DemoStageAsset(kind="facts", title=spec.title, caption=spec.caption, facts=facts))
                continue
            if (
                spec.path is None
                or not spec.path.is_file()
                or spec.path.suffix.lower() not in _ASSET_SUFFIXES[spec.kind]
            ):
                raise SampleExportError(
                    f"Asset {spec.kind} của {stage_id.value} thiếu file hợp lệ "
                    f"({', '.join(sorted(_ASSET_SUFFIXES[spec.kind]))})"
                )
            name = f"{stage_id.value.lower().removeprefix('st-')}-{index}{spec.path.suffix.lower()}"
            stage.assets.append(
                DemoStageAsset(
                    kind=spec.kind,  # type: ignore[arg-type]
                    title=spec.title,
                    caption=spec.caption,
                    file=add_file(out, spec.path, name),
                )
            )


def _export_job_bundle(
    registry: "ProjectRegistry",
    job_id: str,
    out: Path,
    *,
    demo_id: str,
    title: str,
    description: str,
    source: DemoSource,
    frames: int = 12,
    stage_assets: Mapping[StageId, Sequence[StageAssetSpec]] | None = None,
) -> DemoManifest:
    """Dựng bundle vào `out` (đã kiểm tham số); xem `export_job_bundle` cho hợp đồng đầy đủ."""
    if not 2 <= frames <= MAX_FRAMES:
        raise SampleExportError(f"Số frame đại diện phải từ 2 đến {MAX_FRAMES}")
    job = registry.get_job(job_id)
    try:
        preview = registry.get_preview(job_id)  # Verify toàn bộ graph preview.
    except (ArtifactStoreError, ValueError) as error:
        raise SampleExportError("Job chưa có bản xem 3DGS đã xác minh để làm mẫu") from error
    resolver = registry.runtime_resolver
    prepare_out(out)
    splat = add_file(out, resolver.require(preview.delivery_ref), "scene.sog")
    project = registry.get_project(job.project_id)
    video = None
    # Job đã che khuôn mặt/biển số: frame trong bundle là bản đã che, nên không đưa video gốc chưa che ra thư viện công khai.
    if project.input_manifest_ref is not None and sanitized_frame_stage(job) is None:
        if project.input_video is None and project.display_video_ref is not None:
            path = resolver.require(project.display_video_ref)
            if sha256_file(path) != project.display_video_ref.artifact_checksum:
                raise SampleExportError("Video ghép để xem lại sai checksum")
            video = add_file(out, path, "display.mp4")
            video_caption = "Video ghép từ ảnh gốc, chỉ để xem lại"
        else:
            manifest = InputManifest.model_validate_json(resolver.require(project.input_manifest_ref).read_bytes())
            source_video = next(
                (item for item in manifest.files if item.media_type in {"video/mp4", "video/quicktime"}), None
            )
            if source_video is not None:
                path = resolver.resolve(source_video.artifact_uri)
                if sha256_file(path) != source_video.checksum:
                    raise SampleExportError("Video gốc sai checksum")
                video = add_file(out, path, "input" + Path(source_video.original_name).suffix.lower())
            video_caption = (
                "Video ghép từ ảnh gốc, dùng làm đầu vào giả lập và xem lại"
                if source_video is not None and project.display_video_ref is not None
                else None
            )
    else:
        video_caption = None
    frame_files: list[DemoFile] = []
    frame_count = None
    frame_ref = prepared_frame_reference(job)
    if frame_ref is not None:
        frame_set = json.loads(resolver.require(frame_ref).read_text())
        rows = frame_set["frames"]
        frame_count = len(rows)
        for marker in evenly([Path(str(i)) for i in range(len(rows))], frames):
            row = rows[int(marker.name)]
            image = resolver.resolve(row["image"]["artifact_uri"])
            frame_files.append(add_file(out, image, f"frame-{row['frame_id']:06d}.png"))
    cameras = []
    if preview.camera_pose_ref is not None:
        try:
            cameras = camera_markers(preview.camera_pose_ref, resolver.require)
        except Exception:  # noqa: BLE001 - camera chỉ là lớp phụ; thiếu thì bundle vẫn dùng được
            cameras = []
    stages = stage_durations(job, registry.list_job_attempts(job.job_id))
    results = recorded_results(registry, job)
    automatic = {
        stage_id: [StageAssetSpec(kind="facts", facts=tuple(facts))]
        for stage_id, facts in result_facts(results).items()
    }
    collision = results.get("collision_ref")
    if collision and StageId.RGB_GEOMETRY in automatic:
        import trimesh

        path = resolver.require_uri(collision["artifact_uri"], collision["artifact_checksum"])
        mesh = trimesh.load(path, force="mesh", process=False)
        automatic[StageId.RGB_GEOMETRY].append(
            StageAssetSpec(kind="facts", facts=(("Số tam giác của lưới", str(len(mesh.faces))),))
        )
    # Ảnh xem trước chỉ lấy từ artifact đã publish của job, không render ảnh mới.
    for stage in job.stage_artifacts:
        if stage.status != StageStatus.SUCCEEDED or not stage.artifact_uri:
            continue
        if stage.stage_id not in automatic or Path(stage.artifact_uri).suffix.lower() not in _ASSET_SUFFIXES["image"]:
            continue
        automatic[stage.stage_id].append(
            StageAssetSpec(kind="image", path=resolver.require_uri(stage.artifact_uri, stage.artifact_checksum))
        )
    combined = {
        stage_id: [*automatic.get(stage_id, []), *(stage_assets or {}).get(stage_id, [])]
        for stage_id in automatic.keys() | (stage_assets or {}).keys()
    }
    if combined:
        _attach_assets(out, stages, combined)
    if results.get("object_extraction") == "objectify_failed_awaiting_choice":
        for stage in stages:
            if stage.stage_id == StageId.OBJECT_EXTRACT:
                stage.state = "failed"
                stage.summary = "Tách theo vật chưa thành công; scene chưa có vật ứng viên."
    geometry = results.get("object_geometry")
    demo = DemoManifest(
        processing=_job_processing(resolver, job),
        machine=_machine(),
        demo_id=demo_id,
        title=title,
        description=description,
        origin="pipeline_job",
        source=source,
        produced_at=datetime.now(UTC),
        provenance={
            "job_id": job.job_id,
            "input_manifest_checksum": job.input_manifest_checksum,
            "config_checksum": job.config_checksum,
            "runtime_manifest_checksum": job.runtime_manifest_checksum,
            "preview_attempt_id": preview.attempt_id,
            "visual_producer_version": preview.producer_version,
        },
        stages=stages,
        object_geometry=DemoObjectGeometry.model_validate(geometry) if geometry else None,
        video=video,
        video_caption=video_caption,
        frames=frame_files,
        frame_count=frame_count,
        splat=splat,
        cameras=cameras,
        display_rotation_xyzw=preview_display_rotation(registry, job, preview),
    )
    write_manifest(out, demo)
    return demo


def export_job_bundle(
    registry: "ProjectRegistry",
    job_id: str,
    out: Path,
    *,
    demo_id: str,
    title: str,
    description: str,
    source: DemoSource,
    frames: int = 12,
    stage_assets: Mapping[StageId, Sequence[StageAssetSpec]] | None = None,
    recording_dir: Path | None = None,
) -> DemoManifest:
    """Bundle từ job thật: video gốc, frame đại diện, SOG preview, thời lượng từ journal, thẻ kết quả khai báo.

    `out` phải trống. Thành công thì manifest đã được đọc lại và kiểm bằng chính mô hình mà thư viện dùng, nên không
    bao giờ ghi ra bundle mà thư viện không đọc được. Thất bại thì dọn `files/` và `manifest.json` đã tạo, để chạy lại
    được; mọi lỗi dữ liệu đều là `SampleExportError`.
    """
    if out.exists() and any(out.iterdir()):
        # Từ chối trước mọi việc khác và không dọn gì: thư mục này không phải do lần chạy này tạo.
        raise SampleExportError(f"{out} đã có dữ liệu; chọn thư mục mới (không ghi đè bundle cũ)")
    try:
        demo = _export_job_bundle(
            registry,
            job_id,
            out,
            demo_id=demo_id,
            title=title,
            description=description,
            source=source,
            frames=frames,
            stage_assets=stage_assets,
        )
        DemoManifest.model_validate_json((out / "manifest.json").read_text(encoding="utf-8"))
        if registry.persistence is not None and registry.get_job(job_id).status == JobStatus.SUCCEEDED:
            from src.services.orchestration.samples.bundle import DemoBundle
            from src.services.orchestration.samples.workspace import freeze_workspace

            freeze_workspace(registry, DemoBundle(out), recording_dir=recording_dir)
        return demo
    except Exception as error:
        _discard(out)
        if isinstance(error, SampleExportError):
            raise
        if isinstance(error, (ValueError, DemoUnavailableError)):  # gồm ValidationError của manifest
            raise SampleExportError(f"Bundle không hợp lệ: {error}") from error
        raise


def _discard(out: Path) -> None:
    """Xoá phần bundle dở dang (chỉ `files/` và `manifest.json` do mình tạo)."""
    shutil.rmtree(out / "workspace", ignore_errors=True)
    shutil.rmtree(out / "files", ignore_errors=True)
    (out / "manifest.json").unlink(missing_ok=True)


_LOCK_STALE_SECONDS = 3600


def _acquire_publish_lock(library_root: Path, job_id: str) -> Path:
    """Khoá theo job bằng `mkdir` (nguyên tử): hai người xuất cùng một job không dựng hai bundle."""
    lock = library_root / f".publishing-{job_id}"
    for _ in range(2):
        try:
            lock.mkdir()
            return lock
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except FileNotFoundError:
                continue  # người giữ khoá vừa nhả: thử lại ngay
            if age < _LOCK_STALE_SECONDS:
                raise SampleExportError("Job này đang được xuất bởi người khác; thử lại sau ít phút") from None
            shutil.rmtree(lock, ignore_errors=True)  # khoá bỏ lại sau sự cố
    raise SampleExportError("Không lấy được khoá xuất bản demo")


def slugify(text: str) -> str:
    """Chuỗi ASCII an toàn cho tên thư mục/ID: bỏ dấu, thường hoá, nối bằng '-'."""
    folded = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    ascii_text = folded.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def published_sample_id(library_root: Path, job_id: str) -> str | None:
    """ID mẫu trong thư viện được xuất từ `job_id` (theo `provenance.job_id`), nếu có."""
    library = DemoLibrary(library_root)
    for sample_id, bundle in library.bundles().items():
        try:
            if bundle.manifest().provenance.get("job_id") == job_id:
                return sample_id
        except DemoUnavailableError:
            continue
    return None


def _frozen_scene_revision(bundle_root: Path) -> str | None:
    try:
        return json.loads((bundle_root / "workspace/snapshot.json").read_bytes())["head"]["scene_revision"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def restore_unpublished(
    registry: "ProjectRegistry", library_root: Path, job_id: str, *, title: str | None, description: str | None
) -> DemoManifest | None:
    """Mẫu của job đã bị bỏ mà scene (và tên, mô tả nếu có truyền) vẫn y như lúc xuất: gỡ dấu bỏ, không chép lại.

    Chỉ dùng khi xuất bản mới thất bại, để thêm lại vẫn được dù bản chép mới hỏng.
    """
    try:
        current = registry.scene.current(job_id).scene.scene_revision
    except Exception:  # noqa: BLE001 - chưa có scene thì không có gì để so
        return None
    candidates = []
    for child in library_root.iterdir():
        marker = child / UNPUBLISHED_MARKER
        if not (child.is_dir() and marker.is_file()):
            continue
        try:
            manifest = DemoManifest.model_validate_json((child / "manifest.json").read_bytes())
        except (OSError, ValueError):
            continue
        if (
            manifest.demo_id == child.name
            and manifest.provenance.get("job_id") == job_id
            and title in (None, manifest.title)
            and description in (None, manifest.description)
            and _frozen_scene_revision(child) == current
        ):
            candidates.append((marker.stat().st_mtime, child, manifest))
    if not candidates:
        return None
    _, child, manifest = max(candidates, key=lambda item: item[0])
    (child / UNPUBLISHED_MARKER).unlink()
    return manifest


def publish_job_bundle(
    registry: "ProjectRegistry",
    job_id: str,
    library_root: Path,
    *,
    title: str,
    description: str,
    source: DemoSource,
    frames: int = 12,
    recording_dir: Path | None = None,
) -> DemoManifest:
    """Xuất job vào thư viện mẫu: dựng trong thư mục tạm rồi đổi tên một lần, không bao giờ ghi đè.

    Thư mục tạm bắt đầu bằng '.' nên `DemoLibrary` bỏ qua; lỗi giữa chừng thì thư mục tạm bị xoá.
    """
    lock = acquire_publish_lock(library_root, job_id)
    try:
        return _publish_locked(
            registry,
            job_id,
            library_root,
            title=title,
            description=description,
            source=source,
            frames=frames,
            recording_dir=recording_dir,
        )
    finally:
        shutil.rmtree(lock, ignore_errors=True)


def acquire_publish_lock(library_root: Path, job_id: str) -> Path:
    """Giữ khoá xuất của job; khoá còn thì `publication_status` báo đang chuẩn bị mẫu."""
    library_root.mkdir(parents=True, exist_ok=True)
    existing = published_sample_id(library_root, job_id)
    if existing is not None:
        raise AlreadyPublishedError(existing)
    lock = _acquire_publish_lock(library_root, job_id)
    _failure_path(library_root, job_id).unlink(missing_ok=True)
    return lock


def _publish_locked(
    registry: "ProjectRegistry",
    job_id: str,
    library_root: Path,
    *,
    title: str,
    description: str,
    source: DemoSource,
    frames: int,
    recording_dir: Path | None,
) -> DemoManifest:
    existing = published_sample_id(library_root, job_id)
    if existing is not None:
        raise AlreadyPublishedError(existing)
    slug = slugify(title) or "scene"
    demo_id = f"{slug[:60]}-{job_id.removeprefix('job-')[:8]}"
    target = library_root / demo_id
    if (target / UNPUBLISHED_MARKER).exists():
        demo_id = f"{demo_id}-{uuid4().hex[:8]}"
        target = library_root / demo_id
    if target.exists():
        raise SampleExportError(f"Thư viện đã có mẫu {demo_id}")
    temp = library_root / f".tmp-{demo_id}-{uuid4().hex[:8]}"
    try:
        manifest = export_job_bundle(
            registry,
            job_id,
            temp,
            demo_id=demo_id,
            title=title,
            description=description,
            source=source,
            frames=frames,
            recording_dir=recording_dir,
        )
        if target.exists():
            raise SampleExportError(f"Thư viện đã có mẫu {demo_id}")
        temp.rename(target)
    finally:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
    return manifest


def _failure_path(library_root: Path, job_id: str) -> Path:
    return library_root / f".publish-failed-{job_id}.json"


def publication_status(library_root: Path, job_id: str) -> tuple[bool, str | None]:
    """(đang chuẩn bị mẫu, lỗi của lần xuất nền gần nhất) — đọc từ thư viện nên mọi tiến trình API đều thấy."""
    lock = library_root / f".publishing-{job_id}"
    try:
        publishing = lock.is_dir() and time.time() - lock.stat().st_mtime < _LOCK_STALE_SECONDS
    except OSError:
        publishing = False
    try:
        error = json.loads(_failure_path(library_root, job_id).read_text(encoding="utf-8"))["detail"]
    except (OSError, ValueError, KeyError, TypeError):
        error = None
    return publishing, error if isinstance(error, str) else None


def publish_in_background(
    registry: "ProjectRegistry",
    job_id: str,
    library_root: Path,
    lock: Path,
    *,
    title: str,
    description: str,
    source: DemoSource,
    recording_dir: Path | None = None,
    on_published: Callable[[DemoManifest], None] | None = None,
) -> None:
    """Chạy trong luồng nền với khoá đã giữ: xuất bản mới từ job; lỗi thì dùng lại mẫu cũ chưa đổi, không thì ghi lỗi."""
    try:
        try:
            manifest = _publish_locked(
                registry,
                job_id,
                library_root,
                title=title,
                description=description,
                source=source,
                frames=12,
                recording_dir=recording_dir,
            )
        except Exception as error:
            logger.exception("demo publish failed for %s", job_id)
            restored = restore_unpublished(registry, library_root, job_id, title=None, description=None)
            if restored is None:
                detail = str(error) if isinstance(error, SampleExportError) else "Không ghi được vào thư viện mẫu"
                _failure_path(library_root, job_id).write_text(json.dumps({"detail": detail}), encoding="utf-8")
                return
            manifest = restored
        if on_published is not None:
            on_published(manifest)
    except Exception:
        logger.exception("demo publish bookkeeping failed for %s", job_id)
    finally:
        shutil.rmtree(lock, ignore_errors=True)
