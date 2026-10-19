#!/usr/bin/env bash
# Entrypoint của image GPU (Dockerfile.gpu). Nạp <gốc>/runtime.env do install.sh ghi lúc build image (đường dẫn và định
# danh runtime, cùng bố cục với laptop), đặt mặc định của riêng container (DB, ổ /data, thời gian chờ), tìm Vulkan ICD
# của NVIDIA, sinh runtime manifest, rồi chạy một trong các chế độ:
#
#   worker      (mặc định) chỉ chạy worker, nối vào DB + kho file chung của deployment (ADR 0003)
#   stack       API + worker trên chính máy này (SQLite + ổ /data), không có frontend
#   preflight   kiểm máy có đủ công cụ không rồi thoát
#   batch ...   chạy scripts.kaggle.run_job với các tham số theo sau (video → gói job)
#   <lệnh khác> chạy nguyên lệnh đó (vd bash)
#
# Biến do người vận hành cấp qua `docker run -e` / cấu hình instance; không có secret nào nằm trong image.
set -euo pipefail

cd /opt/real2sim/app
ROOT="${R2S_ROOT:-/opt/real2sim}"
STATE="${R2S_STATE:-/data}"
mkdir -p "$STATE"

# Biến Brush do người vận hành cấp (nếu có) phải được giữ, nên ghi nhận trước khi nạp runtime.env.
OPERATOR_BRUSH_ENVIRONMENT="${R2S_BRUSH_ENVIRONMENT:-}"
# Nạp bằng đúng hàm của install.sh: chỉ đặt biến CHƯA có, nên mọi biến người vận hành đã cấp đều thắng.
export REPO="$PWD"
source scripts/gpu/install.d/_lib.sh
load_runtime_env "$ROOT/runtime.env"

ICD=""
for candidate in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do
  [ -f "$candidate" ] && ICD="$candidate"
done
if [ -z "$ICD" ]; then
  # Host không mount file ICD: trỏ thẳng vào thư viện driver (nếu host có cấp phần đồ hoạ của driver).
  ICD="$STATE/nvidia_icd.json"
  echo '{"file_format_version": "1.0.0", "ICD": {"library_path": "libGLX_nvidia.so.0", "api_version": "1.3.0"}}' > "$ICD"
fi
# VK_ICD_FILENAMES phải trỏ tới ICD thật của container này, không phải đường dẫn của máy đã cài runtime.
export R2S_BRUSH_ENVIRONMENT="$OPERATOR_BRUSH_ENVIRONMENT"
if [ -z "$R2S_BRUSH_ENVIRONMENT" ]; then
  export R2S_BRUSH_ENVIRONMENT="{\"RUST_LOG\":\"info,wgpu_core=warn\",\"VK_ICD_FILENAMES\":\"$ICD\"}"
fi
# Node do install.sh cài nằm ngoài PATH mặc định; app gọi `node` từ PATH.
if [ -n "${R2S_NODE_BIN_DIR:-}" ]; then export PATH="$R2S_NODE_BIN_DIR:$PATH"; fi

# Chỉ đặt giá trị mặc định: mọi biến người vận hành đã cấp đều được giữ nguyên.
export APP_ENV="${APP_ENV:-production}"
# Production không được chạy mở: Settings từ chối khởi động nếu thiếu biến này (stack mode cần tài khoản Reviewer đầu tiên).
export AUTH_REQUIRED="${AUTH_REQUIRED:-true}"
export LLM_PROVIDER="${LLM_PROVIDER:-openai}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-not-used-by-studio}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///$STATE/runtime.db}"
export ARTIFACT_ROOT="${ARTIFACT_ROOT:-$STATE/artifacts}"
export PRODUCT_WORKER_ROOT="${PRODUCT_WORKER_ROOT:-$STATE/workers}"
export PRODUCT_PRIVACY_MODE="${PRODUCT_PRIVACY_MODE:-self_attested}"
export PRODUCT_PROCESSING_CONFIG="${PRODUCT_PROCESSING_CONFIG:-/opt/real2sim/app/configs/product/processing_presets_v1.json}"
export PRODUCT_RUNTIME_MANIFEST="${PRODUCT_RUNTIME_MANIFEST:-$STATE/runtime_manifest.json}"
export PRODUCT_PREVIEW_TIMEOUT_SECONDS="${PRODUCT_PREVIEW_TIMEOUT_SECONDS:-36000}"
# Thời gian chờ là chính sách của container (cùng giá trị với scripts/gpu/studio.env.example); đổi bằng -e.
export R2S_COLMAP_TIMEOUT_SECONDS="${R2S_COLMAP_TIMEOUT_SECONDS:-14400}"
export R2S_BRUSH_TIMEOUT_SECONDS="${R2S_BRUSH_TIMEOUT_SECONDS:-21600}"
export R2S_VOXEL_TIMEOUT_SECONDS="${R2S_VOXEL_TIMEOUT_SECONDS:-1800}"
export PRODUCT_GEOMETRY_CONFIG="${PRODUCT_GEOMETRY_CONFIG:-/opt/real2sim/app/configs/product/geometry_indoor_v1.json}"
export PRODUCT_SCENE_TIMEOUT_SECONDS="${PRODUCT_SCENE_TIMEOUT_SECONDS:-3600}"

PY=.venv/bin/python
# Bộ che khuôn mặt/biển số (AUD-18): người vận hành khai thư mục trọng số thì pod tự tải hai file từ kho file của
# deployment và kiểm sha256 (đã có đủ thì không tải lại). Không lấy được thì dừng ngay, vì worker thiếu trọng số
# sẽ làm hỏng mọi job có che.
if [ -n "${PRODUCT_EGOBLUR_WEIGHTS:-}" ]; then
  "$PY" -m scripts.gpu.egoblur_weights fetch --to "$PRODUCT_EGOBLUR_WEIGHTS"
fi
[ -f "$PRODUCT_RUNTIME_MANIFEST" ] || "$PY" -m scripts.gpu.make_runtime_manifest --out "$PRODUCT_RUNTIME_MANIFEST"

# Registry năng lực của luồng nhập mới (AUD-24): sinh từ bản ghi kiểm định đã commit + identity runtime đo ngay trên
# máy này (scripts.gpu.qualify_input_runtimes). Kết quả xác định, không mốc thời gian, nên API và worker dùng chung
# một file mà không lệch chuỗi checksum. Sinh lỗi thì bỏ biến: luồng nhập báo "chưa có bộ xử lý phù hợp" thay vì
# chạy với một registry hỏng. Không bao giờ dùng make_input_runtime_registry (lời khai dev-local) ở đây.
export PRODUCT_INPUT_RUNTIME_REGISTRY="${PRODUCT_INPUT_RUNTIME_REGISTRY:-$STATE/input_runtime_registry.json}"
if ! "$PY" -m scripts.gpu.qualify_input_runtimes --out "$PRODUCT_INPUT_RUNTIME_REGISTRY"; then
  echo "[!] Không sinh được registry năng lực input; luồng nhập mới sẽ báo chưa có bộ xử lý phù hợp." >&2
  unset PRODUCT_INPUT_RUNTIME_REGISTRY
fi

mode="${1:-worker}"
[ "$#" -gt 0 ] && shift
case "$mode" in
  worker)
    if [ -n "${GPU_BOOT_TOKEN:-}" ]; then
      "$PY" -m scripts.kaggle.preflight
    fi
    exec "$PY" -m scripts.gpu.run_workers --workers "${STUDIO_WORKERS:-auto}"
    ;;
  stack)
    "$PY" -m uvicorn src.main:app --host 0.0.0.0 --port "${APP_PORT:-8000}" --no-access-log &
    api=$!
    trap 'kill -TERM "$api" 2>/dev/null || true' EXIT
    "$PY" -m scripts.gpu.run_workers --workers "${STUDIO_WORKERS:-auto}"
    ;;
  preflight)
    exec "$PY" -m scripts.kaggle.preflight
    ;;
  batch)
    exec "$PY" -m scripts.kaggle.run_job "$@"
    ;;
  *)
    exec "$mode" "$@"
    ;;
esac
