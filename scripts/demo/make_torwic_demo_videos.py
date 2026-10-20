"""Ghép ảnh RGB gốc của mọi traversal TorWIC-SLAM thành bộ video demo (mỗi traversal ba video).

Với mỗi traversal tìm thấy dưới `--dataset-root` (thư mục có `image_left/` và `frame_times.txt`):

- `<tên>__left.mp4`       camera trái;
- `<tên>__right.mp4`      camera phải;
- `<tên>__left_right.mp4` camera trái rồi tới camera phải trong cùng một video (cùng đoạn đường, hai góc quay).

FPS lấy từ `frame_times.txt` (không chèn/rớt frame). Video đi qua luồng upload như video người dùng; bộ này là
**dữ liệu demo**, không phải benchmark: nó dùng mọi frame, kể cả frame mà benchmark split giữ lại để đánh giá,
nên không dùng kết quả từ các video này làm số liệu đánh giá. Video ghép hai camera vẫn được
pipeline xử lý như một camera (`single_camera`): chỉ để xem scene, không kỳ vọng chất lượng dựng hình.

    python -m scripts.demo.make_torwic_demo_videos --dataset-root "/media/usb/AI20K/TorWIC SLAM Dataset" \\
        --out "/media/usb/AI20K/P-087 demo videos" [--only Aisle_CCW] [--force]

Ghi `manifest.json` cạnh video: nguồn, số frame, FPS, thời lượng và sha256 của từng file.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

CAMERAS = {"left": "image_left", "right": "image_right"}
#: Thứ tự ghép trong từng biến thể video.
VARIANTS: dict[str, tuple[str, ...]] = {"left": ("left",), "right": ("right",), "left_right": ("left", "right")}


@dataclass(frozen=True)
class Traversal:
    """Một lần chạy của robot: tên dùng cho file video, thư mục chứa ảnh và FPS thật."""

    name: str
    directory: Path
    fps: float
    frames: int


@dataclass(frozen=True)
class VideoRecord:
    """Một video đã ghép, để người dùng và script khác biết nó đến từ đâu."""

    file: str
    traversal: str
    cameras: list[str]
    frames: int
    fps: float
    duration_seconds: float
    sha256: str
    purpose: str = "demo"


def fps_from_times(path: Path) -> float:
    """FPS trung bình từ `frame_times.txt` (mỗi dòng một mốc giây); lỗi rõ ràng nếu thời gian không tăng."""
    times = [float(line) for line in path.read_text().split() if line.strip()]
    if len(times) < 2 or times[-1] <= times[0]:
        raise ValueError(f"{path.name} cần ít nhất 2 mốc thời gian tăng dần")
    return (len(times) - 1) / (times[-1] - times[0])


def slug(name: str) -> str:
    """Tên file an toàn từ tên thư mục traversal (bỏ dấu cách và ký tự lạ)."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def discover(dataset_root: Path) -> list[Traversal]:
    """Mọi traversal có đủ hai camera và mốc thời gian, tìm tới hai cấp thư mục (bản tải về hay lồng thêm một cấp)."""
    found: list[Traversal] = []
    for times in sorted([*dataset_root.glob("*/frame_times.txt"), *dataset_root.glob("*/*/frame_times.txt")]):
        directory = times.parent
        counts = {camera: len(list((directory / folder).glob("*.png"))) for camera, folder in CAMERAS.items()}
        if not all(counts.values()) or len(set(counts.values())) != 1:
            continue  # thiếu một camera hoặc hai camera lệch số frame: không ghép được video đồng bộ
        # Thư mục cha mang ngày chạy (vd `Aisle_CW_Run_1__2022-06-15`) khi bản tải về lồng thêm một cấp.
        label = directory.parent.name if directory.parent != dataset_root else directory.name
        found.append(Traversal(slug(label), directory, fps_from_times(times), counts["left"]))
    return found


def frame_paths(traversal: Traversal, cameras: tuple[str, ...]) -> list[Path]:
    """Ảnh theo đúng thứ tự phát: hết camera này mới tới camera kế."""
    frames: list[Path] = []
    for camera in cameras:
        frames.extend(sorted((traversal.directory / CAMERAS[camera]).glob("*.png")))
    return frames


def encode(frames: list[Path], fps: float, out: Path) -> None:
    """H.264 yuv420p (trình duyệt phát được), cùng thông số với `make_torwic_video`."""
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(".partial.mp4")
    with tempfile.TemporaryDirectory(prefix="torwic_demo_") as directory:
        # Đánh số lại liên tục: image2 demuxer cần dãy không đứt, và video ghép nối hai dãy cùng tên file.
        for index, frame in enumerate(frames):
            (Path(directory) / f"{index:06d}.png").symlink_to(frame.resolve())
        subprocess.run(
            [
                shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-framerate", f"{fps:.6f}", "-i", str(Path(directory) / "%06d.png"),
                "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(partial),
            ],
            check=True,
        )  # fmt: skip
    partial.replace(out)  # đổi tên sau cùng: không bao giờ có video dở ở tên thật


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(dataset_root: Path, out: Path, only: list[str], force: bool) -> list[VideoRecord]:
    """Ghép các video còn thiếu và trả bản ghi của mọi video trong bộ."""
    records: list[VideoRecord] = []
    for traversal in discover(dataset_root):
        if only and traversal.name not in {slug(name) for name in only}:
            continue
        for variant, cameras in VARIANTS.items():
            target = out / f"{traversal.name}__{variant}.mp4"
            frames = frame_paths(traversal, cameras)
            if force or not target.is_file():
                encode(frames, traversal.fps, target)
            records.append(
                VideoRecord(
                    file=target.name,
                    traversal=traversal.name,
                    cameras=list(cameras),
                    frames=len(frames),
                    fps=round(traversal.fps, 6),
                    duration_seconds=round(len(frames) / traversal.fps, 3),
                    sha256=sha256(target),
                )
            )
            print(f"{target.name} · {len(frames)} frame · {traversal.fps:.3f} fps", flush=True)
    return records


def main(argv: list[str] | None = None) -> int:
    """CLI; trả exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", action="append", default=[], help="chỉ ghép traversal này (lặp lại được)")
    parser.add_argument("--force", action="store_true", help="ghép lại cả video đã có")
    args = parser.parse_args(argv)
    records = build(args.dataset_root, args.out, args.only, args.force)
    if not records:
        print("Không tìm thấy traversal nào có đủ image_left, image_right và frame_times.txt")
        return 1
    manifest = {"dataset": "TorWIC-SLAM", "purpose": "demo", "videos": [asdict(record) for record in records]}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(records)} video · manifest: {args.out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
