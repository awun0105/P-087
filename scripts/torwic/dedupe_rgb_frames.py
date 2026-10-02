"""Giữ một bản vật lý cho ảnh RGB mà `raw/` và `normalized/` của TorWIC store cùng chứa.

REC-01 publish `normalized/<traversal>/rgb_frames/*.png` là bản sao nguyên byte của `raw/.../image_left/*.png`; manifest
ràng buộc checksum hai phía bằng nhau. Tool này thay bản sao bằng hardlink tới file raw rồi đặt file dùng chung thành
chỉ đọc. Đường dẫn, bytes, checksum và manifest không đổi, nên consumer và provenance của REC-01 giữ nguyên.

Vì sao hardlink kèm chỉ-đọc: hai tên trỏ cùng một dữ liệu, nên ghi đè tại chỗ qua `normalized/` sẽ sửa luôn `raw/`. Khi
file chỉ đọc, thao tác đó lỗi ngay; còn thay file bằng rename thì chỉ tách liên kết và `raw/` vẫn nguyên. Khác symlink,
hardlink không gãy khi chỉ chép riêng `normalized/` sang máy khác.

Mặc định chỉ báo cáo; thêm `--apply` để gộp. `prepare_dataset` không bị sửa: nếu xoá `normalized/` rồi publish lại thì
ảnh lại là bản sao, khi đó chạy lại tool này.

Ví dụ:
    python -m scripts.torwic.dedupe_rgb_frames --dataset-root data/torwic_slam
    python -m scripts.torwic.dedupe_rgb_frames --dataset-root data/torwic_slam --apply
"""

import argparse
import errno
import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.torwic import prepare_dataset as prep
from scripts.torwic.canonical_dataset import validate_canonical_manifest

_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_TEMP_SUFFIX = ".dedupe-tmp"
# `os.link` trả các mã này khi hai thư mục khác filesystem hoặc filesystem không hỗ trợ hardlink.
_LINK_UNSUPPORTED = frozenset({errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EMLINK})


@dataclass(frozen=True)
class FramePair:
    """Một frame RGB: file gốc trong `raw/` và bản `normalized/` mà manifest ràng buộc cùng checksum."""

    frame_id: int
    raw: Path
    normalized: Path
    checksum: str


@dataclass(frozen=True)
class DedupeReport:
    """Trạng thái lưu trữ ảnh RGB của store, đếm trên đĩa sau lần chạy.

    `shared`: frame chỉ còn một bản vật lý. `duplicated`/`duplicated_bytes`: frame còn hai bản rời và dung lượng thừa.
    `linked`: số frame vừa gộp trong lần chạy này. `writable_shared`: frame dùng chung nhưng còn ghi được (chưa an toàn).
    """

    frame_count: int
    shared: int
    duplicated: int
    duplicated_bytes: int
    linked: int
    writable_shared: int


def load_frame_pairs(dataset_root: Path) -> list[FramePair]:
    """Validate toàn bộ store rồi trả các cặp raw/normalized theo manifest.

    Store không qua validator (bytes, checksum, split, dataset index) thì dừng ở đây, trước khi đụng tới file nào.
    """
    text = (dataset_root / "dataset_manifest.yaml").read_text()
    record = json.loads(text) if text.strip() else {}
    traversals = record.get("traversals") if isinstance(record, dict) else None
    if not traversals:
        raise ValueError("Dataset manifest lists no prepared traversal; run prepare_dataset first")
    pairs: list[FramePair] = []
    for traversal in traversals:
        reference = traversal["preparation_manifest"]
        prep.check_safe_path(reference)
        manifest = validate_canonical_manifest(dataset_root / reference, dataset_root, dataset_root)
        sources = [entry for entry in manifest.source_files if entry.frame_id is not None]
        generated = [entry for entry in manifest.generated_files if entry.frame_id is not None]
        for source, target in zip(sources, generated, strict=True):
            pairs.append(
                FramePair(
                    frame_id=source.frame_id,
                    raw=dataset_root / source.relative_path,
                    normalized=dataset_root / target.relative_path,
                    checksum=source.artifact_checksum,
                )
            )
    return pairs


def _replace_with_link(pair: FramePair) -> None:
    """Thay bản sao normalized bằng hardlink tới raw.

    Hash lại hai phía ngay trước khi thay để không bao giờ ghi đè một file normalized khác nội dung. Link được tạo dưới
    tên tạm rồi rename nguyên tử, nên dừng giữa chừng thì frame vẫn là bản cũ hoặc đã là link, không có trạng thái thiếu.
    """
    if prep.compute_sha256(pair.raw) != pair.checksum or prep.compute_sha256(pair.normalized) != pair.checksum:
        raise ValueError(f"RGB frame {pair.frame_id} changed after validation; nothing replaced")
    temporary = pair.normalized.with_name(f".{pair.normalized.name}{_TEMP_SUFFIX}")
    temporary.unlink(missing_ok=True)
    try:
        os.link(pair.raw, temporary)
    except OSError as error:
        if error.errno in _LINK_UNSUPPORTED:
            raise ValueError("raw/ and normalized/ must be on one filesystem that supports hard links") from error
        raise
    os.replace(temporary, pair.normalized)


def _make_read_only(path: Path) -> None:
    """Bỏ quyền ghi của file dùng chung để ghi đè tại chỗ lỗi ngay thay vì sửa cả raw."""
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & _WRITE_BITS:
        path.chmod(mode & ~_WRITE_BITS)


def _report(pairs: list[FramePair], linked: int) -> DedupeReport:
    """Đếm theo trạng thái thật trên đĩa, không theo việc vừa làm."""
    shared = writable_shared = duplicated_bytes = 0
    for pair in pairs:
        if os.path.samefile(pair.raw, pair.normalized):
            shared += 1
            writable_shared += bool(stat.S_IMODE(pair.raw.stat().st_mode) & _WRITE_BITS)
        else:
            duplicated_bytes += pair.normalized.stat().st_size
    return DedupeReport(
        frame_count=len(pairs),
        shared=shared,
        duplicated=len(pairs) - shared,
        duplicated_bytes=duplicated_bytes,
        linked=linked,
        writable_shared=writable_shared,
    )


def dedupe_rgb_frames(dataset_root: Path, *, apply: bool) -> DedupeReport:
    """Báo cáo ảnh RGB đang lưu hai bản giữa `raw/` và `normalized/`; khi `apply` thì gộp về một bản."""
    pairs = load_frame_pairs(dataset_root)
    linked = 0
    if apply:
        for pair in pairs:
            if not os.path.samefile(pair.raw, pair.normalized):
                _replace_with_link(pair)
                linked += 1
            _make_read_only(pair.raw)
        # Hậu kiểm: đổi cách lưu không được làm store lệch manifest.
        load_frame_pairs(dataset_root)
    return _report(pairs, linked)


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Gộp ảnh RGB trùng giữa raw/ và normalized/ của TorWIC store.")
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Gộp thật; không có cờ này thì chỉ báo cáo")
    args = parser.parse_args()
    try:
        report = dedupe_rgb_frames(args.dataset_root, apply=args.apply)
    except FileNotFoundError as error:
        name = Path(error.filename).name if error.filename else "unknown"
        raise SystemExit(f"Missing required dataset component: {name}") from error
    print(json.dumps(asdict(report), indent=2))


if __name__ == "__main__":
    main()
