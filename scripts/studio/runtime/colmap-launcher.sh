#!/bin/sh
# COLMAP chạy trong container ghim digest (cùng bản đã kiểm trên máy tham chiếu). Chỉ mount thư mục làm việc hiện
# tại, không có mạng. Thêm `--gpus all` nếu bật use_gpu trong thông số xử lý và máy có NVIDIA Container Toolkit.
set -eu
exec docker run --rm --network none --cpus "${R2S_COLMAP_CPUS:-4}" --memory "${R2S_COLMAP_MEMORY:-8g}" \
  --user "$(id -u):$(id -g)" -v "$PWD:$PWD" -w "$PWD" \
  colmap/colmap@sha256:b8498ebecab11c3f9b9a25370e3fcfb6de9b6bcd4f3c85d5dc39a40229f40954 colmap "$@"
