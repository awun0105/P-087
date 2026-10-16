#!/usr/bin/env bash
# splat-transform (npm) và Node chạy nó. Node ghim (--system-node tắt việc này: dùng Node hệ thống, ví dụ laptop qua mise).
recipe_splat() { echo "splat $(pin SPLAT_TRANSFORM_VERSION) node=$(pin NODE_VERSION)/$SYSTEM_NODE"; }

verify_splat() {
  [ -f "$SPLAT_MODULE" ] || return 1
  local version
  version="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$SPLAT_DIR/package.json" | head -n1)"
  [ "$version" = "$(pin SPLAT_TRANSFORM_VERSION)" ] || return 1
  if [ "$SYSTEM_NODE" = 1 ]; then
    command -v node >/dev/null
  else
    [ -x "$NODE_BIN" ] && [ "$("$NODE_BIN" --version)" = "$(pin NODE_VERSION)" ]
  fi
}

install_splat() {
  if [ "$SYSTEM_NODE" = 0 ]; then
    local archive="$TMP_DIR/node.tar.xz"
    mkdir -p "$RECON/node"
    fetch "https://nodejs.org/dist/$(pin NODE_VERSION)/node-$(pin NODE_VERSION)-linux-x64.tar.xz" "$archive" "$(pin NODE_SHA)"
    tar -xJf "$archive" -C "$RECON/node" --strip-components=1
    export PATH="$RECON/node/bin:$PATH"
  fi
  command -v npm >/dev/null || die "không thấy npm; bỏ --system-node để dùng Node ghim"
  mkdir -p "$RECON"
  (cd "$RECON" && npm install --silent --no-audit --no-fund "@playcanvas/splat-transform@$(pin SPLAT_TRANSFORM_VERSION)")
}
