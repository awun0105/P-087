"""Bộ đệm HTTP cho nội dung gắn checksum (T-051): trình duyệt giữ vĩnh viễn, hỏi lại thì trả 304.

Chỉ dùng `private`: mọi request vẫn qua kiểm quyền trước khi trả 304 hay nội dung.
"""

from fastapi import Request

IMMUTABLE_PRIVATE = "private, max-age=31536000, immutable"


def checksum_etag(checksum: str) -> str:
    """ETag mạnh từ checksum nội dung (bỏ tiền tố `sha256:`)."""
    return '"' + checksum.removeprefix("sha256:") + '"'


def not_modified(request: Request, etag: str) -> bool:
    """Trình duyệt đã có đúng bản này (`If-None-Match` chứa ETag, hoặc `*`)."""
    header = request.headers.get("if-none-match")
    if not header:
        return False
    tags = {tag.strip().removeprefix("W/") for tag in header.split(",")}
    return etag in tags or "*" in tags
