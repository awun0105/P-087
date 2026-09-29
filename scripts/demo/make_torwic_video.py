"""Ghép frame RGB đã chuẩn hóa của một traversal TorWIC thành video MP4 để upload.

Video dùng đúng FPS suy từ `timestamps.csv` (không tự chèn/rớt frame), đi qua
luồng upload như video người dùng. Chỉ đọc `normalized/`, không đụng
`evaluation_only/`.

    python -m scripts.demo.make_torwic_video --sequence-dir data/torwic_slam/normalized/aisle_cw \\
        --out data/demo/tmp/aisle_cw.mp4 [--start 0 --count 400]
"""

import argparse
import csv
import shutil
import subprocess
import tempfile
from pathlib import Path


def sequence_fps(timestamps: Path) -> float:
    """FPS trung bình từ timestamps; lỗi rõ ràng nếu thời gian không tăng."""
    with timestamps.open(newline="") as stream:
        rows = [float(row["timestamp_sec"]) for row in csv.DictReader(stream)]
    if len(rows) < 2 or rows[-1] <= rows[0]:
        raise SystemExit("timestamps.csv cần ít nhất 2 mốc tăng dần")
    return (len(rows) - 1) / (rows[-1] - rows[0])


def main() -> None:
    """Chọn đoạn frame liên tiếp rồi encode H.264 yuv420p (trình duyệt phát được)."""
    parser = argparse.ArgumentParser(description="Build an upload video from TorWIC normalized frames")
    parser.add_argument("--sequence-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=None)
    args = parser.parse_args()
    frames = sorted((args.sequence_dir / "rgb_frames").glob("*.png"))
    selected = frames[args.start : None if args.count is None else args.start + args.count]
    if len(selected) < 2:
        raise SystemExit("Cần ít nhất 2 frame")
    fps = sequence_fps(args.sequence_dir / "timestamps.csv")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="torwic_video_") as directory:
        # Đánh số lại liên tục để image2 demuxer không bỏ frame khi đoạn không bắt đầu từ 0.
        for index, frame in enumerate(selected):
            (Path(directory) / f"{index:06d}.png").symlink_to(frame.resolve())
        subprocess.run(
            [
                shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-framerate", f"{fps:.6f}", "-i", str(Path(directory) / "%06d.png"),
                "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(args.out),
            ],
            check=True,
        )  # fmt: skip
    print(f"{args.out} · {len(selected)} frame · {fps:.3f} fps")


if __name__ == "__main__":
    main()
