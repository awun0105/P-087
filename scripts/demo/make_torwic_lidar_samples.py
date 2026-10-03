"""Dựng bộ mẫu **video + gói LiDAR** từ TorWIC-SLAM cho luồng B và C của Studio (ADR 0009).

Với một đoạn `[--start, --start + --count)` của một traversal, tạo ba file khớp nhau từng frame:

- `<tên>__left.mp4`              video camera trái của đúng đoạn đó (frame *i* của video = ảnh `start + i`);
- `<tên>__lidar_scans.zip`       luồng C: scan `.pcd` thô (mỗi `--scan-step` frame một scan, tên là chỉ số frame trong
                                  đoạn) + quỹ đạo + calibration + thời điểm frame;
- `<tên>__lidar_registered.zip`  luồng B: một đám mây đã ghép từ chính các scan đó + ba file đi kèm như trên.

Quỹ đạo và thời điểm frame được cắt đúng theo đoạn nên dòng *i* luôn ứng với frame *i* của video — đây là quy ước
của gói LiDAR. Quỹ đạo là `traj_gt.txt` của dataset (**ground truth**): khi tạo scene phải khai "quỹ đạo chuẩn của
dataset". Bộ mẫu là dữ liệu demo, dùng mọi frame của đoạn (kể cả frame mà benchmark split giữ lại để đánh giá), nên
không dùng kết quả từ nó làm số liệu đánh giá (DATASET_PLAYBOOK).

    python -m scripts.demo.make_torwic_lidar_samples --dataset-root "/media/usb/AI20K/TorWIC SLAM Dataset" \\
        --traversal Aisle_CW --start 100 --count 500 --out "/media/usb/AI20K/P-087 lidar samples"
"""

import argparse
import io
import json
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.demo.make_torwic_demo_videos import discover, encode, sha256, slug
from src.services.reconstruction.lidar.fusion import FusionConfig, fuse_scans, parse_trajectory, ply_bytes, read_points

COMPANIONS = ("traj_gt.txt", "frame_times.txt", "calibrations.txt")


@dataclass(frozen=True)
class SampleRecord:
    """Một file của bộ mẫu và luồng Studio mà nó phục vụ."""

    file: str
    flow: str
    traversal: str
    start: int
    count: int
    scans: int
    size_bytes: int
    sha256: str
    trajectory_origin: str = "ground_truth"


def segment_lines(text: str, start: int, count: int) -> str:
    """Các dòng `[start, start + count)` của file mỗi-dòng-một-frame; thiếu dòng thì báo lỗi, không cắt ngắn lặng lẽ."""
    lines = [line for line in text.splitlines() if line.strip()]
    if start < 0 or count < 2 or start + count > len(lines):
        raise ValueError(f"đoạn [{start}, {start + count}) vượt quá {len(lines)} frame của traversal")
    return "\n".join(lines[start : start + count]) + "\n"


def scan_indices(count: int, step: int) -> list[int]:
    """Chỉ số frame (trong đoạn) có scan đi kèm: 0, step, 2·step, …"""
    if step < 1:
        raise ValueError("--scan-step phải ≥ 1")
    return list(range(0, count, step))


def _zip(path: Path, members: dict[str, bytes | Path]) -> None:
    """ZIP không nén (đám mây điểm nén kém, và máy chủ đọc theo đoạn nhanh hơn); ghi qua file tạm rồi đổi tên."""
    partial = path.with_suffix(".partial.zip")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in members.items():
            if isinstance(payload, Path):
                archive.write(payload, name)
            else:
                archive.writestr(name, payload)
    partial.replace(path)


def build(
    dataset_root: Path, traversal_name: str, start: int, count: int, scan_step: int, out: Path
) -> list[SampleRecord]:
    """Tạo ba file của một bộ mẫu và trả bản ghi của chúng."""
    traversal = next((item for item in discover(dataset_root) if item.name == slug(traversal_name)), None)
    if traversal is None:
        raise ValueError(f"không thấy traversal {traversal_name} dưới {dataset_root}")
    calibration = next(
        (
            path
            for path in (traversal.directory.parent / "calibrations.txt", dataset_root / "calibrations.txt")
            if path.is_file()
        ),
        None,
    )
    if calibration is None or not (traversal.directory / "traj_gt.txt").is_file():
        raise ValueError("traversal thiếu traj_gt.txt hoặc dataset thiếu calibrations.txt")
    trajectory = segment_lines((traversal.directory / "traj_gt.txt").read_text(), start, count)
    times = segment_lines((traversal.directory / "frame_times.txt").read_text(), start, count)
    companions: dict[str, bytes | Path] = {
        "traj_gt.txt": trajectory.encode(),
        "frame_times.txt": times.encode(),
        "calibrations.txt": calibration.read_bytes(),
    }
    indices = scan_indices(count, scan_step)
    scans = {index: traversal.directory / "lidar" / f"{start + index:06d}.pcd" for index in indices}
    missing = [path.name for path in scans.values() if not path.is_file()]
    if missing:
        raise ValueError(f"thiếu scan: {missing[:5]}")
    out.mkdir(parents=True, exist_ok=True)
    name = f"{traversal.name}_{start}_{start + count - 1}"
    video = out / f"{name}__left.mp4"
    frames = [traversal.directory / "image_left" / f"{start + index:06d}.png" for index in range(count)]
    encode(frames, traversal.fps, video)
    raw = out / f"{name}__lidar_scans.zip"
    _zip(raw, {**companions, **{f"lidar/{index:06d}.pcd": path for index, path in scans.items()}})
    poses = parse_trajectory(trajectory)

    def clouds():  # noqa: ANN202 - generator cục bộ
        for index, path in scans.items():
            with path.open("rb") as stream:
                yield read_points(stream, FusionConfig().max_scan_points), poses[index]

    cloud, stats = fuse_scans(clouds(), FusionConfig())
    registered = out / f"{name}__lidar_registered.zip"
    _zip(registered, {**companions, "registered_lidar.ply": ply_bytes(cloud)})
    print(f"{name}: {count} frame · {len(scans)} scan → {stats.point_count:,} điểm".replace(",", "."))
    return [
        SampleRecord(path.name, flow, traversal.name, start, count, len(scans), path.stat().st_size, sha256(path))
        for path, flow in ((video, "video"), (raw, "C: scan thô + quỹ đạo"), (registered, "B: LiDAR đã đăng ký"))
    ]


def main(argv: list[str] | None = None) -> int:
    """CLI; trả exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--traversal", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=500, help="số frame của đoạn (mặc định 500 ≈ 50 giây)")
    parser.add_argument(
        "--scan-step", type=int, default=5, help="cứ N frame lấy một scan (giữ gói dưới giới hạn upload)"
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        records = build(args.dataset_root, args.traversal, args.start, args.count, args.scan_step, args.out)
    except (OSError, ValueError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    manifest = args.out / "manifest.json"
    existing = json.loads(manifest.read_text()) if manifest.is_file() else {"samples": []}
    kept = [item for item in existing["samples"] if item["file"] not in {record.file for record in records}]
    payload = {
        "note": "Quỹ đạo là ground truth của TorWIC: khi tạo scene chọn 'Quỹ đạo chuẩn của dataset'. Dữ liệu demo, không phải benchmark.",
        "samples": [*kept, *(asdict(record) for record in records)],
    }
    buffer = io.StringIO()
    json.dump(payload, buffer, ensure_ascii=False, indent=2)
    manifest.write_text(buffer.getvalue() + "\n", encoding="utf-8")
    print(f"{len(records)} file · manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
