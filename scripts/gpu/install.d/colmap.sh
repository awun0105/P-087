#!/usr/bin/env bash
# COLMAP 4.x. Hai chế độ: docker (launcher gọi image ghim theo digest, như máy local) và binary (gói nhị phân từ kho
# file của deployment hoặc --colmap-from-file; xuất bởi scripts/gpu/export_colmap_binary.sh). Pod không cần Docker ở chế độ binary.
recipe_colmap() { echo "colmap $COLMAP_MODE $(pin COLMAP_IMAGE) $(pin COLMAP_BINARY_SHA)"; }

verify_colmap() {
  case "$COLMAP_MODE" in
    docker)
      [ -f "$COLMAP_LAUNCHER" ] && grep -qF "$(pin COLMAP_IMAGE)" "$COLMAP_LAUNCHER" && grep -qF "docker run" "$COLMAP_LAUNCHER"
      ;;
    binary)
      [ -x "$COLMAP_BINARY_WRAPPER" ] \
        && "$COLMAP_BINARY_WRAPPER" help 2>&1 | grep -q "^COLMAP 4\." \
        && "$COLMAP_BINARY_WRAPPER" pose_prior_mapper -h 2>&1 | grep -q -- "--prior_position_std_x"
      ;;
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
    binary)
      # Đã có sẵn cây COLMAP đã giải nén (image COPY vào <gốc>/colmap) thì chỉ tạo wrapper; không thì tải và giải nén.
      if [ ! -x "$GOC/colmap/bin/colmap" ]; then
        command -v zstd >/dev/null || die "cần zstd để giải nén gói COLMAP (apt: zstd)"
        local bundle="$TMP_DIR/colmap-bundle.tar.zst"
        local from=()
        [ -n "${COLMAP_FROM_FILE:-}" ] && from=(--from-file "$COLMAP_FROM_FILE")
        "$(py_bin)" -m scripts.gpu.colmap_binary fetch --out "$bundle" "${from[@]}"
        mkdir -p "$GOC/colmap"
        zstd -dc "$bundle" | tar -x -C "$GOC/colmap" --strip-components=1
      fi
      mkdir -p "$(dirname "$COLMAP_BINARY_WRAPPER")"
      cat > "$COLMAP_BINARY_WRAPPER" <<WRAPPER
#!/bin/sh
LD_LIBRARY_PATH="$GOC/colmap/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}" exec "$GOC/colmap/bin/colmap" "\$@"
WRAPPER
      chmod +x "$COLMAP_BINARY_WRAPPER"
      ;;
  esac
}
