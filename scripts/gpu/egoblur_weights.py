"""Đưa trọng số EgoBlur Gen2 (AUD-18) lên kho file của deployment và tải về pod worker.

Meta chỉ cho tải hai file `.jit` sau khi đồng ý giấy phép, nên image GPU không chứa chúng. Người vận hành tải
một lần, chạy `upload` một lần; từ đó mọi pod mới tự `fetch` lúc khởi động (entrypoint gọi), không chép tay:

    python -m scripts.gpu.egoblur_weights upload --from /đường/dẫn/thư_mục_chứa_hai_file
    python -m scripts.gpu.egoblur_weights fetch  --to   /data/egoblur

Dùng chính kho file `ARTIFACT_S3_*` của deployment (bucket riêng tư, cùng prefix). Cả hai chiều đều kiểm sha256
với giá trị ghim dưới đây, nên file sai hoặc hỏng không bao giờ được dùng.
"""

import argparse
import sys
from pathlib import Path

from src.config import get_settings
from src.services.orchestration.artifacts import ArtifactRemote, ArtifactStoreError, sha256_file
from src.services.orchestration.storage import artifact_remote

#: Cùng giá trị với `scripts/gpu/setup_scene_runtime.sh`.
WEIGHTS = {
    "ego_blur_face_gen2.jit": "sha256:2ba183ff74a66752f6457846efb4379b351727d1c9eaef461ed4be8db18cc2e8",
    "ego_blur_lp_gen2.jit": "sha256:1d6b3fc37fce4158d3b7d4a364290cfeeccc86a9cd84a376c443d560f11497f4",
}
REMOTE_DIR = "runtime-weights/egoblur-gen2"


class WeightsError(RuntimeError):
    """Thiếu file, sai checksum hoặc chưa cấu hình kho file."""


def _valid(path: Path, checksum: str) -> bool:
    return path.is_file() and sha256_file(path) == checksum


def upload(remote: ArtifactRemote, source: Path) -> list[str]:
    """Đẩy hai file từ `source`; idempotent. Trả tên các file vừa đẩy hoặc đã có sẵn trên kho."""
    for name, checksum in WEIGHTS.items():
        if not _valid(source / name, checksum):
            raise WeightsError(
                f"{source / name}: thiếu file hoặc sai checksum, tải lại từ projectaria.com/tools/egoblur"
            )
    for name in WEIGHTS:
        remote.push(f"{REMOTE_DIR}/{name}", source / name)
    return list(WEIGHTS)


def fetch(remote: ArtifactRemote | None, target: Path) -> list[str]:
    """Bảo đảm `target` có đủ hai file đúng checksum; chỉ tải file còn thiếu. Trả tên các file vừa tải."""
    downloaded = []
    for name, checksum in WEIGHTS.items():
        path = target / name
        if _valid(path, checksum):
            continue
        if remote is None:
            raise WeightsError(f"{path}: thiếu trọng số và deployment chưa cấu hình kho file ARTIFACT_S3_*")
        path.unlink(missing_ok=True)  # file hỏng hoặc tải dở từ lần trước
        try:
            remote.fetch(f"{REMOTE_DIR}/{name}", path, checksum)
        except ArtifactStoreError as error:
            raise WeightsError(
                f"{name}: không tải được từ kho file ({error}). Chạy `egoblur_weights upload` một lần từ máy có file."
            ) from error
        downloaded.append(name)
    return downloaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("upload").add_argument("--from", dest="path", type=Path, required=True)
    commands.add_parser("fetch").add_argument("--to", dest="path", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        remote = artifact_remote(get_settings())
        if args.command == "upload":
            if remote is None:
                raise WeightsError("Chưa cấu hình kho file ARTIFACT_S3_*")
            print("[egoblur] đã có trên kho file:", ", ".join(upload(remote, args.path)))
        else:
            done = fetch(remote, args.path)
            print("[egoblur] trọng số sẵn sàng tại", args.path, "(vừa tải: " + (", ".join(done) or "không") + ")")
    except (WeightsError, ArtifactStoreError, ValueError) as error:
        print(f"[!] EgoBlur: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
