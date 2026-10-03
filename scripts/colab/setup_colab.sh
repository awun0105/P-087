#!/usr/bin/env bash
# Cài đặt runtime pipeline trên Google Colab GPU (Tesla T4/L4/A100).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE="${1:-/content/r2s}"
RUNTIME="$STATE/runtime"
BRUSH_VERSION="0.3.0"
BRUSH_URL="https://github.com/ArthurBrussee/brush/releases/download/v${BRUSH_VERSION}/brush-app-x86_64-unknown-linux-gnu.tar.xz"
BRUSH_SHA="4f0f9a8785d1951c62df26aae247c02c5bba32b00f40b06df4e1c9b867399e20"
NODE_VERSION="v22.20.0"
SPLAT_TRANSFORM_VERSION="3.6.6"

mkdir -p "$STATE" "$RUNTIME"
cd "$ROOT"

echo "[1/6] Cài đặt gói hệ thống (COLMAP, ffmpeg, Vulkan, libnvidia-gl-580)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq colmap ffmpeg libvulkan1 vulkan-tools xz-utils curl git libnvidia-gl-580 >/dev/null

echo "[2/6] Kiểm tra Vulkan ICD cho NVIDIA..."
ICD="/usr/share/vulkan/icd.d/nvidia_icd.json"
if [ ! -f "$ICD" ]; then
  for candidate in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do
    [ -f "$candidate" ] && ICD="$candidate"
  done
fi

echo "[3/6] Đồng bộ môi trường Python 3.12..."
[ -x .venv/bin/python ] || uv venv --python 3.12 .venv
uv pip sync --python .venv/bin/python requirements.lock.txt

echo "[4/6] Cài đặt Brush ${BRUSH_VERSION}..."
if [ ! -x "$RUNTIME/brush/brush_app" ]; then
  curl -L --fail -o "$RUNTIME/brush.tar.xz" "$BRUSH_URL"
  [ "$(sha256sum "$RUNTIME/brush.tar.xz" | cut -d' ' -f1)" = "$BRUSH_SHA" ] || { echo "[!] Sai checksum Brush" >&2; exit 1; }
  mkdir -p "$RUNTIME/brush" && tar -xJf "$RUNTIME/brush.tar.xz" -C "$RUNTIME/brush" --strip-components=1
  rm "$RUNTIME/brush.tar.xz"
fi

echo "[5/6] Cài đặt Node ${NODE_VERSION} + splat-transform ${SPLAT_TRANSFORM_VERSION}..."
if [ ! -x "$RUNTIME/node/bin/node" ]; then
  curl -L --fail -o "$RUNTIME/node.tar.xz" "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.xz"
  mkdir -p "$RUNTIME/node" && tar -xJf "$RUNTIME/node.tar.xz" -C "$RUNTIME/node" --strip-components=1
  rm "$RUNTIME/node.tar.xz"
fi
export PATH="$RUNTIME/node/bin:$PATH"
[ -d "$RUNTIME/node_modules/@playcanvas/splat-transform" ] || \
  (cd "$RUNTIME" && npm install --silent "@playcanvas/splat-transform@${SPLAT_TRANSFORM_VERSION}")
SPLAT="$RUNTIME/node_modules/@playcanvas/splat-transform"

echo "[6/6] Tạo file env + runtime manifest..."
ENV_FILE="$STATE/colab.env"
COLMAP_VERSION="$(dpkg-query -W -f='${Version}' colmap 2>/dev/null || echo '3.9.1')"
cat > "$ENV_FILE" <<EOF
# Cấu hình runtime trên Google Colab
PATH=$RUNTIME/node/bin:$PATH
APP_ENV=production
LLM_PROVIDER=openai
OPENAI_API_KEY=not-used-by-studio
DATABASE_URL=sqlite:///$STATE/runtime.db
ARTIFACT_ROOT=$STATE/artifacts
PRODUCT_WORKER_ROOT=$STATE/workers
PRODUCT_PRIVACY_MODE=self_attested
PRODUCT_PROCESSING_CONFIG=$ROOT/configs/product/processing_presets_v1.json
PRODUCT_RUNTIME_MANIFEST=$STATE/runtime_manifest.json
PRODUCT_PREVIEW_TIMEOUT_SECONDS=21600
REC03_COLMAP_COMMAND='["colmap"]'
REC03_COLMAP_RUNTIME_IDENTITY=colmap-apt-$COLMAP_VERSION
REC03_COLMAP_TIMEOUT_SECONDS=7200
REC04_BRUSH_COMMAND='["$RUNTIME/brush/brush_app"]'
REC04_BRUSH_EXPECTED_VERSION=$BRUSH_VERSION
REC04_BRUSH_ENVIRONMENT='{"RUST_LOG":"info,wgpu_core=warn","VK_ICD_FILENAMES":"$ICD"}'
REC04_BRUSH_RUNTIME_IDENTITY=brush-v${BRUSH_VERSION}-linux-archive-sha256:$BRUSH_SHA
REC04_BRUSH_TIMEOUT_SECONDS=14400
REC04_SPLAT_DEVICE=gpu
REC04_SPLAT_MODULE_PATH=$SPLAT/dist/index.mjs
REC05_VOXEL_CLI=$SPLAT/bin/cli.mjs
REC05_VOXEL_MODULE_PATH=$SPLAT/dist/index.mjs
REC05_VOXEL_TIMEOUT_SECONDS=1800
PRODUCT_GEOMETRY_CONFIG=$ROOT/configs/product/geometry_v1.json
PRODUCT_SCENE_TIMEOUT_SECONDS=3600
EOF

set -a; source "$ENV_FILE"; set +a
.venv/bin/python -m scripts.gpu.make_runtime_manifest --out "$PRODUCT_RUNTIME_MANIFEST"

echo "=== Setup hoàn tất thành công trên Colab ==="
echo "Môi trường lưu tại: $ENV_FILE"
echo "Runtime manifest lưu tại: $PRODUCT_RUNTIME_MANIFEST"
