"""Đưa bộ mẫu (video + gói LiDAR) vào danh sách file đã tải của Studio để chọn ngay ở trang Dựng từ video.

    python -m scripts.studio.seed_samples --dir "/media/usb/AI20K/P-087 lidar samples"

File đi qua đúng đường nhận upload của sản phẩm (nhận diện theo nội dung, checksum, giới hạn dung lượng) và được ghi
"tải lên bởi Bộ mẫu TorWIC". Chạy lại không tạo bản trùng: file đã có (cùng tên và checksum) được bỏ qua. Cấu hình kho
lấy từ môi trường như API (`DATABASE_URL`, `ARTIFACT_ROOT`) — với stack local: `set -a; . scripts/gpu/studio.env`.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from src.config import get_settings
from src.services.orchestration.artifacts import ArtifactResolver
from src.services.orchestration.auth import Actor
from src.services.orchestration.jobs.database import RuntimeDatabase
from src.services.orchestration.uploads import UPLOAD_EXTENSIONS, UploadError, UploadRecord
from src.services.orchestration.uploads.service import VideoUploadService

SAMPLE_ACTOR = Actor(user_id="sample-library", display_name="Bộ mẫu TorWIC")
_CHUNK = 8 * 1024 * 1024


def _checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def seed(directory: Path, service: VideoUploadService) -> list[UploadRecord]:
    """Thêm mọi file mẫu chưa có; trả các bản ghi vừa thêm."""
    existing = {(record.original_name, record.checksum) for record in service.list()}
    added: list[UploadRecord] = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in UPLOAD_EXTENSIONS or not path.is_file():
            continue
        if (path.name, _checksum(path)) in existing:
            print(f"[mẫu] đã có: {path.name}")
            continue
        pending = service.begin(path.name)
        try:
            with path.open("rb") as stream:
                while chunk := stream.read(_CHUNK):
                    pending.publication.write(chunk)
            record = service.finish(pending, SAMPLE_ACTOR)
        finally:
            pending.publication.abort()
        added.append(record)
        print(f"[mẫu] thêm {path.name} → {record.input_kind}")
    return added


def main(argv: list[str] | None = None) -> int:
    """CLI; trả exit code."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, required=True, help="thư mục chứa .mp4 và gói .zip của bộ mẫu")
    args = parser.parse_args(argv)
    if not args.dir.is_dir():
        print(f"Không thấy thư mục mẫu: {args.dir}", file=sys.stderr)
        return 1
    settings = get_settings()
    service = VideoUploadService(
        RuntimeDatabase(settings.database_url),
        ArtifactResolver(settings.artifact_root),
        settings.product_upload_max_bytes,
    )
    try:
        added = seed(args.dir, service)
    except UploadError as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 1
    print(f"{len(added)} file mẫu mới.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
