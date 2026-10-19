"""Gói nhị phân COLMAP 4.x (T-038): đẩy lên kho file của deployment một lần, pod tự tải về rồi kiểm sha256.

Cùng mẫu với scripts/gpu/egoblur_weights.py. Gói được xuất bởi scripts/gpu/export_colmap_binary.sh; sha256 ghim trong
configs/runtime/pins.env (COLMAP_BINARY_SHA). Cả hai chiều đều kiểm sha256 này, nên gói sai hay hỏng không bao giờ
được dùng. Khoá của kho file lấy từ ARTIFACT_S3_* như các phần khác của hệ thống; không có khoá thì dùng --from-file.

    python -m scripts.gpu.colmap_binary upload --from <colmap-bundle.tar.zst>
    python -m scripts.gpu.colmap_binary fetch  --out  <đường_dẫn.tar.zst> [--from-file <colmap-bundle.tar.zst>]
"""

import argparse
import shutil
import sys
from pathlib import Path

from src.config import get_settings
from src.services.orchestration.artifacts import ArtifactRemote, ArtifactStoreError, sha256_file
from src.services.orchestration.storage import artifact_remote

REPO = Path(__file__).resolve().parents[2]
PINS = REPO / "configs/runtime/pins.env"
BUNDLE_NAME = "colmap-bundle.tar.zst"


class BundleError(RuntimeError):
    """Thiếu file, sai checksum, hoặc chưa cấu hình kho file."""


def pinned(key: str, pins: Path = PINS) -> str:
    for line in pins.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    raise BundleError(f"thiếu {key} trong configs/runtime/pins.env")


def remote_path(image: str) -> str:
    """Thư mục trên kho theo digest của image COLMAP: đổi image thì đổi thư mục, không ghi đè gói cũ."""
    digest = image.split("@sha256:", 1)[-1]
    return f"runtime-binaries/colmap-{digest[:12]}/{BUNDLE_NAME}"


def _valid(path: Path, checksum: str) -> bool:
    return path.is_file() and sha256_file(path) == checksum


def upload(remote: ArtifactRemote, source: Path, key: str) -> str:
    """Đẩy gói lên kho sau khi kiểm sha256 ghim. Trả khoá trên kho."""
    checksum = f"sha256:{key}"
    if not _valid(source, checksum):
        raise BundleError(f"{source}: thiếu file hoặc sai sha256 so với COLMAP_BINARY_SHA")
    target = remote_path(pinned("COLMAP_IMAGE"))
    remote.push(target, source)
    return target


def fetch(remote: ArtifactRemote | None, out: Path, key: str, from_file: Path | None = None) -> bool:
    """Bảo đảm `out` là gói đúng sha256. Trả True nếu vừa tải/sao chép, False nếu đã đúng sẵn."""
    checksum = f"sha256:{key}"
    if _valid(out, checksum):
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    if from_file is not None:
        if not _valid(from_file, checksum):
            raise BundleError(f"{from_file}: sai sha256 so với COLMAP_BINARY_SHA")
        shutil.copyfile(from_file, out)
        return True
    if remote is None:
        raise BundleError(f"{out}: chưa có gói và deployment chưa cấu hình kho file ARTIFACT_S3_* (dùng --from-file)")
    try:
        remote.fetch(remote_path(pinned("COLMAP_IMAGE")), out, checksum)
    except ArtifactStoreError as error:
        raise BundleError(
            f"không tải được gói COLMAP từ kho file ({error}). Chạy `upload` một lần từ máy có gói đúng sha256."
        ) from error
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("upload").add_argument("--from", dest="source", type=Path, required=True)
    fetch_parser = commands.add_parser("fetch")
    fetch_parser.add_argument("--out", type=Path, required=True)
    fetch_parser.add_argument("--from-file", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        key = pinned("COLMAP_BINARY_SHA")
        remote = artifact_remote(get_settings())
        if args.command == "upload":
            if remote is None:
                raise BundleError("chưa cấu hình kho file ARTIFACT_S3_*")
            print("[colmap] đã đẩy lên", upload(remote, args.source, key.split(":")[-1]))
        else:
            downloaded = fetch(remote, args.out, key.split(":")[-1], args.from_file)
            print("[colmap] gói sẵn sàng tại", args.out, "(vừa lấy về)" if downloaded else "(đã đúng sẵn)")
    except (BundleError, ArtifactStoreError, ValueError) as error:
        print(f"[!] COLMAP: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
