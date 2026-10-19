#!/usr/bin/env bash
# Xuất gói nhị phân COLMAP 4.x từ image ghim (cùng digest với máy local dùng qua docker) để pod không cần Docker.
#
#   scripts/gpu/export_colmap_binary.sh <out.tar.zst>
#
# Lấy đúng các file mà stage `colmap` của Dockerfile.gpu chép (binary + thư viện đi kèm), kèm giấy phép của COLMAP
# (BSD) và onnxruntime (MIT) tải từ kho mã chính thức theo sha ghim. Kết quả có cấu trúc colmap/bin, colmap/lib,
# colmap/LICENSES. In sha256 để ghi vào configs/runtime/pins.env (COLMAP_BINARY_SHA).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO
[ -n "${1:-}" ] || { echo "dùng: export_colmap_binary.sh <out.tar.zst>" >&2; exit 2; }
OUT="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
command -v docker >/dev/null || { echo "[!] cần Docker để lấy binary từ image" >&2; exit 1; }
command -v zstd >/dev/null || { echo "[!] cần zstd" >&2; exit 1; }
source "$REPO/scripts/gpu/install.d/_lib.sh"

IMAGE="$(pin COLMAP_IMAGE)"
WORK="$(mktemp -d)"
CONTAINER=""
cleanup() {
  [ -n "$CONTAINER" ] && docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

CONTAINER="$(docker create "$IMAGE")"
mkdir -p "$WORK/colmap/bin" "$WORK/colmap/lib" "$WORK/colmap/LICENSES"
docker cp -L "$CONTAINER:/usr/local/bin/colmap" "$WORK/colmap/bin/colmap"
for path in /usr/local/lib/libonnxruntime.so.1 /usr/local/lib/libonnxruntime_providers_shared.so \
            /usr/local/cuda/lib64/libcudart.so.12 /usr/local/cuda/lib64/libOpenCL.so.1; do
  docker cp -L "$CONTAINER:$path" "$WORK/colmap/lib/"
done
chmod +x "$WORK/colmap/bin/colmap"
fetch "$(pin COLMAP_LICENSE_URL)" "$WORK/colmap/LICENSES/COLMAP-LICENSE.txt" "$(pin COLMAP_LICENSE_SHA)"
fetch "$(pin ONNXRUNTIME_LICENSE_URL)" "$WORK/colmap/LICENSES/onnxruntime-LICENSE.txt" "$(pin ONNXRUNTIME_LICENSE_SHA)"

tar -C "$WORK" -cf - colmap | zstd -19 -T0 -q -f -o "$OUT"
echo "[xuất] $OUT"
echo "sha256 $(sha_of "$OUT")"
echo "kích thước $(stat -c %s "$OUT") byte"
