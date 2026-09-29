"""TorWIC offline adapter: publish quality mask mà không di chuyển RGB."""

import argparse
import json
import os
import tempfile
from pathlib import Path

from scripts.torwic import prepare_dataset as prep
from scripts.torwic.canonical_dataset import validate_canonical_manifest
from src.models.contracts.identity import verify_content_checksum
from src.services.reconstruction.rgb.preflight.ffmpeg_probe import FFmpegRGBProbe
from src.services.reconstruction.rgb.preflight.quality import RGBQualityRequest, RGBQualityValidator
from src.services.reconstruction.rgb.preflight.quality_models import RGBFrameAsset, RGBQualityProfile, RGBQualityReport


def build_request(dataset_root: Path, traversal_id: str, profile: RGBQualityProfile) -> RGBQualityRequest:
    """Chỉ lấy frozen reconstruction IDs để đo quality."""
    traversal = traversal_id.lower()
    derived = dataset_root / "derived" / traversal
    manifest = validate_canonical_manifest(derived / "preparation_manifest.json", dataset_root, dataset_root)
    split = prep.BenchmarkSplit(**json.loads((derived / "benchmark_split.json").read_text()))
    verify_content_checksum(split, "split_checksum")
    entries = {item.frame_id: item for item in manifest.generated_files if item.frame_id is not None}
    frames = tuple(
        RGBFrameAsset(
            frame_id=frame_id,
            path=dataset_root / entries[frame_id].relative_path,
            checksum=entries[frame_id].artifact_checksum,
            timestamp_sec=entries[frame_id].timestamp_sec,
        )
        for frame_id in split.train_frame_ids
    )
    return RGBQualityRequest(
        frames=frames,
        source_manifest_checksum=manifest.manifest_checksum,
        selection_checksum=split.split_checksum,
        profile=profile,
    )


def publish_report(path: Path, report: RGBQualityReport) -> None:
    """Publish atomic, immutable; chạy lại cùng output là idempotent."""
    payload = report.model_dump_json(indent=2).encode("utf-8") + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("existing REC-02 quality report differs; create a new versioned output")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".rec02_")
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    """Chạy profile đã duyệt trên canonical dataset và publish mask."""
    parser = argparse.ArgumentParser(description="Create an immutable TorWIC REC-02 quality report")
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--traversal-id", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    profile = RGBQualityProfile.model_validate_json(args.profile.read_text())
    root = args.dataset_root.resolve()
    request = build_request(root, args.traversal_id, profile)
    report = RGBQualityValidator(FFmpegRGBProbe()).validate(request)
    path = root / "derived" / args.traversal_id.lower() / "quality_report.json"
    publish_report(path, report)
    print(
        json.dumps(
            {
                "selected": len(report.selected_frame_ids),
                "excluded": len(report.excluded_frame_ids),
                "effective": len(report.effective_reconstruction_frame_ids),
                "report_checksum": report.report_checksum,
                "motion_warnings": report.motion.warnings,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
