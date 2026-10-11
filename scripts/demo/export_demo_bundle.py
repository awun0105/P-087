"""Export demo bundle cho Studio từ một job đã chạy thật (hoặc bản smoke tạm).

Chạy trên máy đã xử lý job (GPU), rồi copy thư mục output sang máy demo và đặt
`PRODUCT_DEMO_DIR` trỏ tới nó. Ví dụ:

    python -m scripts.demo.export_demo_bundle job --job-id job-abc --out data/demo/current
    python -m scripts.demo.export_demo_bundle smoke --sog scene.sog --frames-dir images \\
        --out data/demo/current --note "Smoke 10 frame, chỉ để dựng UI"

Thêm thẻ kết quả cho từng bước (ảnh, video, số đo thật) bằng `--stage-assets assets.json`, ví dụ:

    {"ST-METRIC-CANONICALIZE": [
        {"kind": "image", "title": "Điểm đo", "path": "metric.png"},
        {"kind": "facts", "facts": [{"label": "Khoảng cách A–B", "value": "1.20 m"}]}]}

Không bao giờ ghi đè bundle cũ; không đọc `evaluation_only`. Logic xuất nằm ở
`src/services/orchestration/samples/export.py` (cũng là thứ nút "Đặt làm bản demo" gọi).
"""

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from src.services.orchestration.jobs.progress import MVP_PIPELINE
from src.services.orchestration.samples import DemoManifest, DemoSource, DemoStage
from src.services.orchestration.samples.export import (
    SampleExportError,
    add_file,
    evenly,
    export_job_bundle,
    load_stage_assets,
    prepare_out,
    stage_durations,
    write_manifest,
)

__all__ = ["export_job", "export_smoke", "main", "stage_durations"]


def _write(out: Path, manifest: DemoManifest) -> None:
    write_manifest(out, manifest)
    print(json.dumps({"demo_dir": str(out), "files": len(manifest.files())}))


def export_job(args: argparse.Namespace) -> None:
    """Bundle từ job thật: video gốc, frame đại diện, SOG preview, thời lượng từ journal."""
    from src.services.orchestration.projects.registry import get_project_registry

    try:
        assets = load_stage_assets(args.stage_assets) if args.stage_assets else None
        manifest = export_job_bundle(
            get_project_registry(),
            args.job_id,
            args.out,
            demo_id=args.demo_id,
            title=args.title,
            description=args.description,
            source=DemoSource(dataset=args.dataset, sequence=args.sequence, note=args.note),
            frames=args.frames,
            stage_assets=assets,
        )
    except SampleExportError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps({"demo_dir": str(args.out), "files": len(manifest.files())}))


def export_smoke(args: argparse.Namespace) -> None:
    """Bundle tạm từ file có sẵn; `origin=smoke_run`, không có thời lượng stage."""
    try:
        prepare_out(args.out)
    except SampleExportError as error:
        raise SystemExit(str(error)) from error
    splat = add_file(args.out, args.sog, "scene" + args.sog.suffix.lower())
    images = sorted(p for p in args.frames_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"})
    frames = [
        add_file(args.out, image, f"frame-{i:06d}{image.suffix.lower()}")
        for i, image in enumerate(evenly(images, args.frames))
    ]
    video = add_file(args.out, args.video, "input" + args.video.suffix.lower()) if args.video else None
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
    job.add_argument("--stage-assets", type=Path, default=None, help="assets.json: thẻ kết quả theo bước")
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
