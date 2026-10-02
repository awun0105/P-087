#!/usr/bin/env bash
# Cài mọi thứ Studio cần trên một máy mới, không phụ thuộc đường dẫn của máy nào. Chạy lại bao nhiêu lần cũng được:
# bước nào đã xong thì bỏ qua.
#
#   scripts/studio/bootstrap.sh            # app (Python + frontend) + runtime xử lý nếu máy có GPU NVIDIA và Docker
#   scripts/studio/bootstrap.sh --app      # chỉ app: đủ để mở Studio và xem dữ liệu đã có (không chạy job mới)
#   scripts/studio/bootstrap.sh --runtime  # buộc cài runtime xử lý (Brush, splat-transform, image COLMAP)
#
# Thường gọi qua `make -f Makefile.studio start` (cài + khôi phục dữ liệu + chạy).
# Không cài gói hệ thống (apt) và không cần sudo: thiếu công cụ nền thì in lệnh cài rồi dừng.
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
mode="${1:-auto}"

BRUSH_VERSION=0.3.0
BRUSH_SHA256=4f0f9a8785d1951c62df26aae247c02c5bba32b00f40b06df4e1c9b867399e20
BRUSH_URL="https://github.com/ArthurBrussee/brush/releases/download/v${BRUSH_VERSION}/brush-app-x86_64-unknown-linux-gnu.tar.xz"
COLMAP_IMAGE="colmap/colmap@sha256:b8498ebecab11c3f9b9a25370e3fcfb6de9b6bcd4f3c85d5dc39a40229f40954"
UV_VERSION=0.9.4
runtime="$root/data/rec04_runtime"
tools="$root/data/tools"

say() { printf '\033[1m[setup]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[setup] %s\033[0m\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ── 1. Công cụ nền ──────────────────────────────────────────────────────────────────────────────
missing=()
for tool in git curl ffmpeg node npm tar; do have "$tool" || missing+=("$tool"); done
if [ "${#missing[@]}" -gt 0 ]; then
  fail "Thiếu: ${missing[*]}. Ubuntu/Debian: sudo apt install git curl ffmpeg xz-utils zstd; Node 20+: https://nodejs.org (hoặc nvm install 22)."
fi
node_major="$(node -p 'process.versions.node.split(".")[0]')"
[ "$node_major" -ge 20 ] || fail "Cần Node 20 trở lên (đang có $(node --version))."

# ── 2. Python: uv tự tải Python 3.12 nếu máy chưa có, rồi cài đúng lockfile ───────────────────────
if have uv; then
  uv_bin="$(command -v uv)"
else
  uv_bin="$tools/uv"
  if [ ! -x "$uv_bin" ]; then
    say "Tải uv $UV_VERSION vào data/tools (không cài vào hệ thống)…"
    mkdir -p "$tools"
    curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" \
      | env UV_INSTALL_DIR="$tools" UV_UNMANAGED_INSTALL="$tools" INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null
    [ -x "$uv_bin" ] || fail "Không tải được uv; cài tay: https://docs.astral.sh/uv/getting-started/installation/"
  fi
fi
lock_stamp="$root/.venv/.r2s-lock-stamp"
lock_sum="$(cat requirements.lock.txt requirements-dev.lock.txt | sha256sum | cut -d' ' -f1)"
if [ ! -x .venv/bin/python ] || [ "$(cat "$lock_stamp" 2>/dev/null || true)" != "$lock_sum" ]; then
  say "Cài môi trường Python 3.12 từ lockfile…"
  [ -x .venv/bin/python ] || "$uv_bin" venv --python 3.12 .venv
  "$uv_bin" pip sync --python .venv/bin/python requirements.lock.txt requirements-dev.lock.txt
  echo "$lock_sum" > "$lock_stamp"
else
  say "Python: đã cài, lockfile không đổi."
fi
[ -f .env ] || { cp .env.example .env; say "Đã tạo .env từ .env.example (điền API key nếu dùng phần chat)."; }

# ── 3. Frontend ─────────────────────────────────────────────────────────────────────────────────
web_stamp="$root/frontend/node_modules/.r2s-lock-stamp"
web_sum="$(sha256sum frontend/package-lock.json | cut -d' ' -f1)"
if [ "$(cat "$web_stamp" 2>/dev/null || true)" != "$web_sum" ]; then
  say "Cài thư viện frontend (npm ci)…"
  (cd frontend && npm ci --no-audit --no-fund)
  echo "$web_sum" > "$web_stamp"
else
  say "Frontend: đã cài, lockfile không đổi."
fi
if [ ! -f frontend/public/editor/index.html ]; then
  say "Build trình chỉnh Gaussian nhúng (SuperSplat, chỉ lần đầu)…"
  (cd frontend && npm run build:editor)
fi

# ── 4. Runtime xử lý (chỉ cần khi muốn chạy job mới; xem scene có sẵn thì không cần) ─────────────
gpu_ready=false
if have nvidia-smi && nvidia-smi -L >/dev/null 2>&1 && have docker && docker info >/dev/null 2>&1; then gpu_ready=true; fi
case "$mode" in
  --app) install_runtime=false ;;
  --runtime) install_runtime=true ;;
  auto) install_runtime=$gpu_ready ;;
  *) fail "Tham số không hợp lệ: $mode (dùng --app hoặc --runtime)" ;;
esac
if [ "$install_runtime" = true ]; then
  [ "$(uname -sm)" = "Linux x86_64" ] || fail "Runtime xử lý (Brush) chỉ có bản Linux x86_64; máy này dùng --app để xem."
  have docker || fail "Runtime xử lý cần Docker (COLMAP chạy trong container)."
  mkdir -p "$runtime"
  brush="$runtime/brush/brush-app-x86_64-unknown-linux-gnu/brush_app"
  if [ ! -x "$brush" ]; then
    say "Tải Brush $BRUSH_VERSION và kiểm checksum…"
    archive="$(mktemp --suffix=.tar.xz)"
    curl -L --fail --progress-bar -o "$archive" "$BRUSH_URL"
    echo "$BRUSH_SHA256  $archive" | sha256sum -c - >/dev/null || { rm -f "$archive"; fail "Checksum Brush không khớp."; }
    mkdir -p "$runtime/brush" && tar -xJf "$archive" -C "$runtime/brush" && rm -f "$archive"
    [ -x "$brush" ] || fail "Giải nén Brush xong nhưng không thấy brush_app."
  fi
  if [ ! -f "$runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs" ] \
     || ! cmp -s scripts/studio/runtime/package-lock.json "$runtime/package-lock.json"; then
    say "Cài splat-transform (phiên bản ghim)…"
    cp scripts/studio/runtime/package.json scripts/studio/runtime/package-lock.json "$runtime/"
    (cd "$runtime" && npm ci --no-audit --no-fund)
  fi
  install -m 0755 scripts/studio/runtime/colmap-launcher.sh "$runtime/colmap-launcher.sh"
  if ! docker image inspect "$COLMAP_IMAGE" >/dev/null 2>&1; then
    say "Tải image COLMAP (vài GB, chỉ lần đầu)…"
    docker pull "$COLMAP_IMAGE"
  fi
  say "Runtime xử lý: sẵn sàng. Tách vật thể + đề xuất tỉ lệ cần thêm: scripts/gpu/setup_scene_runtime.sh data/scene_runtime"
else
  say "Bỏ qua runtime xử lý (không có GPU NVIDIA + Docker, hoặc chạy --app): Studio mở ở chế độ chỉ xem."
fi
say "Xong."
