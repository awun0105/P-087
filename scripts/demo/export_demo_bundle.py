"""Export demo bundle cho Studio từ một job đã chạy thật (hoặc bản smoke tạm).

Chạy trên máy đã xử lý job (GPU), rồi copy thư mục output sang máy demo và đặt
`PRODUCT_DEMO_DIR` trỏ tới nó. Ví dụ:

    python -m scripts.demo.export_demo_bundle job --job-id job-abc --out data/demo/current
    python -m scripts.demo.export_demo_bundle smoke --sog scene.sog --frames-dir images \\
        --out data/demo/current --note "Smoke 10 frame, chỉ để dựng UI"

Không bao giờ ghi đè bundle cũ; không đọc `evaluation_only`.
"""

import argparse
import json
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from src.models.contracts.manifests import InputManifest, JobManifest, JobStatus, StageStatus
from src.services.orchestration.artifacts import sha256_file
from src.services.orchestration.demo import DemoFile, DemoManifest, DemoSource, DemoStage
from src.services.orchestration.jobs.dispatch import prepared_frame_reference
from src.services.orchestration.jobs.models import JobAttemptRecord
from src.services.orchestration.jobs.progress import MVP_PIPELINE

_MEDIA = {".mp4": "video/mp4", ".mov": "video/quicktime", ".png": "image/png", ".jpg": "image/jpeg"}
_MEDIA.update({".jpeg": "image/jpeg", ".sog": "application/octet-stream", ".ply": "application/octet-stream"})


def stage_durations(job: JobManifest, attempts: Sequence[JobAttemptRecord]) -> list[DemoStage]:
    """Thời lượng thật từng stage: chuỗi completed_at, mốc đầu là lúc attempt RUNNING.

    Stage không có mốc hoàn tất (hoặc mốc lệch) để null thay vì đoán.
    """
    latest = attempts[-1].attempt if attempts else 1
    running = [event for event in attempts if event.attempt == latest and event.status == JobStatus.RUNNING]
    cursor = running[0].recorded_at if running else None
    done = {
        stage.stage_id: stage.completed_at
        for stage in job.stage_artifacts
        if stage.status == StageStatus.SUCCEEDED and stage.completed_at is not None
    }
    stages = []
    for stage_id in MVP_PIPELINE:
        end = done.get(stage_id)
        duration = (end - cursor).total_seconds() if end is not None and cursor is not None else None
        stages.append(DemoStage(stage_id=stage_id, duration_seconds=duration if duration and duration >= 0 else None))
        cursor = end or cursor
    return stages


def _add(out: Path, source: Path, name: str) -> DemoFile:
    target = out / "files" / name
    shutil.copyfile(source, target)
    return DemoFile(
        name=name,
        media_type=_MEDIA.get(target.suffix.lower(), "application/octet-stream"),
        size_bytes=target.stat().st_size,
        checksum=sha256_file(target),
    )


def _evenly(items: Sequence[Path], count: int) -> list[Path]:
    if len(items) <= count:
        return list(items)
    step = (len(items) - 1) / (count - 1)
    return [items[round(i * step)] for i in range(count)]


def _prepare_out(out: Path) -> None:
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} đã có dữ liệu; chọn thư mục mới (không ghi đè bundle cũ)")
    (out / "files").mkdir(parents=True, exist_ok=True)


def _write(out: Path, manifest: DemoManifest) -> None:
    (out / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"demo_dir": str(out), "files": len(manifest.files())}))


def export_job(args: argparse.Namespace) -> None:
    """Bundle từ job thật: video gốc, frame đại diện, SOG preview, thời lượng từ journal."""
    from src.services.orchestration.projects.registry import get_project_registry

    registry = get_project_registry()
    job = registry.get_job(args.job_id)
    preview = registry.get_preview(args.job_id)  # Verify toàn bộ graph preview.
    resolver = registry.runtime_resolver
    _prepare_out(args.out)
    splat = _add(args.out, resolver.require(preview.delivery_ref), "scene.sog")
    project = registry.get_project(job.project_id)
    video = None
    if project.input_manifest_ref is not None:
        manifest = InputManifest.model_validate_json(resolver.require(project.input_manifest_ref).read_bytes())
        source = manifest.files[0]
        path = resolver.resolve(source.artifact_uri)
        if sha256_file(path) != source.checksum:
            raise SystemExit("Video gốc sai checksum")
        video = _add(args.out, path, "input" + Path(source.original_name).suffix.lower())
    frames: list[DemoFile] = []
    frame_count = None
    frame_ref = prepared_frame_reference(job)
    if frame_ref is not None:
        frame_set = json.loads(resolver.require(frame_ref).read_text())
        rows = frame_set["frames"]
        frame_count = len(rows)
        picked = _evenly([Path(str(i)) for i in range(len(rows))], args.frames)
        for marker in picked:
            row = rows[int(marker.name)]
            image = resolver.resolve(row["image"]["artifact_uri"])
            frames.append(_add(args.out, image, f"frame-{row['frame_id']:06d}.png"))
    _write(
        args.out,
        DemoManifest(
            demo_id=args.demo_id,
            title=args.title,
            description=args.description,
            origin="pipeline_job",
            source=DemoSource(dataset=args.dataset, sequence=args.sequence, note=args.note),
            produced_at=datetime.now(UTC),
            provenance={
                "job_id": job.job_id,
                "input_manifest_checksum": job.input_manifest_checksum,
                "config_checksum": job.config_checksum,
                "runtime_manifest_checksum": job.runtime_manifest_checksum,
                "preview_attempt_id": preview.attempt_id,
                "visual_producer_version": preview.producer_version,
            },
            stages=stage_durations(job, registry.list_job_attempts(job.job_id)),
            video=video,
            frames=frames,
            frame_count=frame_count,
            splat=splat,
        ),
    )


def export_smoke(args: argparse.Namespace) -> None:
    """Bundle tạm từ file có sẵn; `origin=smoke_run`, không có thời lượng stage."""
    _prepare_out(args.out)
    splat = _add(args.out, args.sog, "scene" + args.sog.suffix.lower())
    images = sorted(p for p in args.frames_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"})
    frames = [
        _add(args.out, image, f"frame-{i:06d}{image.suffix.lower()}")
        for i, image in enumerate(_evenly(images, args.frames))
    ]
    video = _add(args.out, args.video, "input" + args.video.suffix.lower()) if args.video else None
    _write(
        args.out,
        DemoManifest(
            demo_id=args.demo_id,
            title=args.title,
            description=args.description,
            origin="smoke_run",
            source=DemoSource(dataset=args.dataset, sequence=args.sequence, note=args.note),
            produced_at=datetime.now(UTC),
            provenance={"sog_checksum": splat.checksum},
            stages=[DemoStage(stage_id=stage_id) for stage_id in MVP_PIPELINE],
            video=video,
            frames=frames,
            frame_count=len(images),
            splat=splat,
        ),
    )


def main(argv: Sequence[str] | None = None) -> None:
    """CLI: `job` cho bundle chính thức, `smoke` cho bản tạm khi chưa chạy GPU."""
    parser = argparse.ArgumentParser(description="Export Studio demo bundle")
    parser.add_argument("--demo-id", default="torwic-aisle-cw")
    parser.add_argument("--title", default="Kho TorWIC · Aisle CW")
    parser.add_argument("--description", default="Lối đi trong kho, quay bằng camera di chuyển trên robot.")
    parser.add_argument("--dataset", default="TorWIC-SLAM")
    parser.add_argument("--sequence", default="Aisle_CW")
    parser.add_argument("--note", default="")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--out", type=Path, required=True)
    modes = parser.add_subparsers(dest="mode", required=True)
    job = modes.add_parser("job")
    job.add_argument("--job-id", required=True)
    smoke = modes.add_parser("smoke")
    smoke.add_argument("--sog", type=Path, required=True)
    smoke.add_argument("--frames-dir", type=Path, required=True)
    smoke.add_argument("--video", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.frames < 2:
        raise SystemExit("--frames phải >= 2")
    (export_job if args.mode == "job" else export_smoke)(args)


if __name__ == "__main__":
    main()
