#!/usr/bin/env bash
# COLMAP 4.x. Hai chế độ: docker (launcher gọi image ghim theo digest, như máy local) và binary (gói nhị phân từ R2).
recipe_colmap() { echo "colmap $COLMAP_MODE $(pin COLMAP_IMAGE)"; }

verify_colmap() {
  case "$COLMAP_MODE" in
    docker) [ -f "$COLMAP_LAUNCHER" ] && grep -qF "$(pin COLMAP_IMAGE)" "$COLMAP_LAUNCHER" && grep -qF "docker run" "$COLMAP_LAUNCHER" ;;
    binary) return 1 ;;
  esac
}

install_colmap() {
  case "$COLMAP_MODE" in
    docker)
      mkdir -p "$RECON"
      cat > "$COLMAP_LAUNCHER" <<LAUNCHER
#!/bin/sh
set -eu
exec docker run --rm --network none --cpus 4 --memory 8g --user "\$(id -u):\$(id -g)" \\
  -v "\$PWD:\$PWD" -w "\$PWD" \\
  $(pin COLMAP_IMAGE) colmap "\$@"
LAUNCHER
      chmod +x "$COLMAP_LAUNCHER"
      ;;
    binary) die "--colmap=binary chưa có (bước 2 của T-038)" ;;
  esac
}
