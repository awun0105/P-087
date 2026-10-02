#!/usr/bin/env bash
# Cài toàn bộ runtime pipeline trên một máy GPU KHÔNG có Docker (Kaggle notebook; cũng dùng được cho
# GPU thuê dạng container). Không đụng luồng chính: chỉ cài công cụ và ghi một file env riêng.
#
#   bash scripts/kaggle/setup_kaggle.sh [thư_mục_state]      # mặc định: /kaggle/tmp/r2s
#   set -a; source <state>/kaggle.env; set +a
#   .venv/bin/python -m scripts.kaggle.preflight
#
# Khác máy local: COLMAP cài bằng apt (chạy CPU, không qua container), Vulkan ICD của NVIDIA tự ghi nếu
# image chưa có. CHƯA chạy thử trên Kaggle (2026-10-01): bước nào hỏng thì `preflight` sẽ chỉ ra.
# Cần: quyền root (apt), Internet bật trong notebook, GPU bật.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# /kaggle/working bị giới hạn 20 GB (là output của notebook); runtime + workspace để ở /kaggle/tmp (~60 GB, không
# được lưu lại). Chỉ gói job xuất ra mới nên nằm trong /kaggle/working.
STATE="${1:-/kaggle/tmp/r2s}"
RUNTIME="$STATE/runtime"
BRUSH_VERSION="0.3.0"
BRUSH_URL="https://github.com/ArthurBrussee/brush/releases/download/v${BRUSH_VERSION}/brush-app-x86_64-unknown-linux-gnu.tar.xz"
BRUSH_SHA="4f0f9a8785d1951c62df26aae247c02c5bba32b00f40b06df4e1c9b867399e20"
NODE_VERSION="v22.20.0"
SPLAT_TRANSFORM_VERSION="3.6.6"
mkdir -p "$STATE" "$RUNTIME"
cd "$ROOT"

echo "[1/7] gói hệ thống (COLMAP, ffmpeg, Vulkan)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq colmap ffmpeg libvulkan1 vulkan-tools xz-utils curl git >/dev/null

echo "[2/7] Vulkan ICD cho NVIDIA…"
ICD=""
for candidate in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do
  [ -f "$candidate" ] && ICD="$candidate"
done
if [ -z "$ICD" ]; then
  # Image không kèm file ICD: trỏ thẳng vào thư viện driver đã được mount vào container.
  ldconfig -p | grep -q libGLX_nvidia.so.0 || echo "[!] Không thấy libGLX_nvidia.so.0 — Vulkan có thể không dùng được GPU." >&2
  ICD="$RUNTIME/nvidia_icd.json"
  cat > "$ICD" <<'JSON'
{"file_format_version": "1.0.0", "ICD": {"library_path": "libGLX_nvidia.so.0", "api_version": "1.3.0"}}
JSON
fi

echo "[3/7] uv + venv của app (Python 3.12, theo lockfile)…"
command -v uv >/dev/null || pip install -q uv
[ -x .venv/bin/python ] || uv venv --python 3.12 .venv
uv pip sync --python .venv/bin/python requirements.lock.txt
PY_INCLUDE="$(.venv/bin/python -c "import sysconfig; print(sysconfig.get_paths()['include'])")"

echo "[4/7] Brush ${BRUSH_VERSION}…"
if [ ! -x "$RUNTIME/brush/brush_app" ]; then
  curl -L --fail -o "$RUNTIME/brush.tar.xz" "$BRUSH_URL"
  [ "$(sha256sum "$RUNTIME/brush.tar.xz" | cut -d' ' -f1)" = "$BRUSH_SHA" ] || { echo "[!] Sai checksum Brush" >&2; exit 1; }
  mkdir -p "$RUNTIME/brush" && tar -xJf "$RUNTIME/brush.tar.xz" -C "$RUNTIME/brush" --strip-components=1
  rm "$RUNTIME/brush.tar.xz"
fi

echo "[5/7] Node ${NODE_VERSION} + splat-transform ${SPLAT_TRANSFORM_VERSION}…"
if [ ! -x "$RUNTIME/node/bin/node" ]; then
  curl -L --fail -o "$RUNTIME/node.tar.xz" "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.xz"
  mkdir -p "$RUNTIME/node" && tar -xJf "$RUNTIME/node.tar.xz" -C "$RUNTIME/node" --strip-components=1
  rm "$RUNTIME/node.tar.xz"
fi
export PATH="$RUNTIME/node/bin:$PATH"
[ -d "$RUNTIME/node_modules/@playcanvas/splat-transform" ] || \
  (cd "$RUNTIME" && npm install --silent "@playcanvas/splat-transform@${SPLAT_TRANSFORM_VERSION}")
SPLAT="$RUNTIME/node_modules/@playcanvas/splat-transform"

echo "[6/7] runtime tách theo vật (SAM2, gsplat, CoACD, LaMa)…"
[ -d /usr/local/cuda/bin ] && export PATH="/usr/local/cuda/bin:$PATH"
CPATH="$PY_INCLUDE" bash scripts/gpu/setup_scene_runtime.sh "$STATE/scene_runtime"

echo "[7/7] file env + runtime manifest…"
ENV_FILE="$STATE/kaggle.env"
COLMAP_VERSION="$(dpkg-query -W -f='${Version}' colmap)"
cat > "$ENV_FILE" <<EOF
# Sinh bởi scripts/kaggle/setup_kaggle.sh — môi trường stack trên máy này (không có secret).
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
PRODUCT_SCENE_RUNTIME_PYTHON=$STATE/scene_runtime/bin/python
PRODUCT_SAM2_CHECKPOINT=$STATE/scene_runtime/checkpoints/sam2.1_hiera_tiny.pt
PRODUCT_LAMA_CHECKPOINT=$STATE/scene_runtime/weights/big-lama.pt
REC06_MOGE_PYTHON=$STATE/scene_runtime/bin/python
REC06_MOGE_MODEL=$STATE/scene_runtime/weights/moge-2-vitb-normal.pt
REC04_BRUSH_LPIPS_PYTHON=$STATE/scene_runtime/bin/python
PRODUCT_SCENE_TIMEOUT_SECONDS=3600
EOF
set -a; source "$ENV_FILE"; set +a
.venv/bin/python -m scripts.gpu.make_runtime_manifest --out "$PRODUCT_RUNTIME_MANIFEST"

echo
echo "Xong. Kiểm máy rồi chạy:"
echo "  set -a; source $ENV_FILE; set +a"
echo "  .venv/bin/python -m scripts.kaggle.preflight"
