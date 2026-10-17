#!/usr/bin/env bash
# Brush (3DGS trainer): archive chính thức theo phiên bản và sha256 ghim. Giữ nguyên cấu trúc thư mục của archive.
recipe_brush() { echo "brush $(pin BRUSH_VERSION) $(pin BRUSH_SHA)"; }

verify_brush() {
  [ -x "$BRUSH_BIN" ] && "$BRUSH_BIN" --version 2>/dev/null | grep -qxF "brush-cli $(pin BRUSH_VERSION)"
}

install_brush() {
  local archive="$TMP_DIR/brush.tar.xz"
  mkdir -p "$RECON/brush"
  fetch "https://github.com/ArthurBrussee/brush/releases/download/v$(pin BRUSH_VERSION)/brush-app-x86_64-unknown-linux-gnu.tar.xz" \
    "$archive" "$(pin BRUSH_SHA)"
  tar -xJf "$archive" -C "$RECON/brush"
}
