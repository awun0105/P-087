#!/usr/bin/env bash
# Entrypoint của image GPU (Dockerfile.gpu). Đặt các đường dẫn công cụ đã cài trong image, tìm Vulkan ICD của
# NVIDIA, sinh runtime manifest, rồi chạy một trong các chế độ:
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
RUNTIME="${R2S_RUNTIME:-/opt/real2sim/runtime}"
SCENE="${R2S_SCENE_RUNTIME:-/opt/real2sim/scene_runtime}"
STATE="${R2S_STATE:-/data}"
SPLAT="$RUNTIME/node_modules/@playcanvas/splat-transform"
mkdir -p "$STATE"

ICD=""
for candidate in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do
  [ -f "$candidate" ] && ICD="$candidate"
done
if [ -z "$ICD" ]; then
  # Host không mount file ICD: trỏ thẳng vào thư viện driver (nếu host có cấp phần đồ hoạ của driver).
  ICD="$STATE/nvidia_icd.json"
  echo '{"file_format_version": "1.0.0", "ICD": {"library_path": "libGLX_nvidia.so.0", "api_version": "1.3.0"}}' > "$ICD"
fi

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
export PRODUCT_PREVIEW_TIMEOUT_SECONDS="${PRODUCT_PREVIEW_TIMEOUT_SECONDS:-21600}"
DEFAULT_COLMAP_COMMAND='["colmap"]'
export REC03_COLMAP_COMMAND="${REC03_COLMAP_COMMAND:-$DEFAULT_COLMAP_COMMAND}"
# Định danh = digest của image COLMAP mà binary được lấy ra (cùng giá trị với máy local dùng image đó qua docker).
COLMAP_DIGEST="${R2S_COLMAP_IMAGE##*@}"
export REC03_COLMAP_RUNTIME_IDENTITY="${REC03_COLMAP_RUNTIME_IDENTITY:-colmap-image-${COLMAP_DIGEST:-unknown}}"
export REC03_COLMAP_TIMEOUT_SECONDS="${REC03_COLMAP_TIMEOUT_SECONDS:-7200}"
DEFAULT_BRUSH_COMMAND="[\"$RUNTIME/brush/brush_app\"]"
export REC04_BRUSH_COMMAND="${REC04_BRUSH_COMMAND:-$DEFAULT_BRUSH_COMMAND}"
export REC04_BRUSH_EXPECTED_VERSION="${REC04_BRUSH_EXPECTED_VERSION:-0.3.0}"
DEFAULT_BRUSH_ENVIRONMENT="{\"RUST_LOG\":\"info,wgpu_core=warn\",\"VK_ICD_FILENAMES\":\"$ICD\"}"
export REC04_BRUSH_ENVIRONMENT="${REC04_BRUSH_ENVIRONMENT:-$DEFAULT_BRUSH_ENVIRONMENT}"
export REC04_BRUSH_RUNTIME_IDENTITY="${REC04_BRUSH_RUNTIME_IDENTITY:-brush-v0.3.0-linux-archive-sha256:4f0f9a8785d1951c62df26aae247c02c5bba32b00f40b06df4e1c9b867399e20}"
export REC04_BRUSH_TIMEOUT_SECONDS="${REC04_BRUSH_TIMEOUT_SECONDS:-14400}"
export REC04_SPLAT_DEVICE="${REC04_SPLAT_DEVICE:-gpu}"
export REC04_SPLAT_MODULE_PATH="${REC04_SPLAT_MODULE_PATH:-$SPLAT/dist/index.mjs}"
export REC05_VOXEL_CLI="${REC05_VOXEL_CLI:-$SPLAT/bin/cli.mjs}"
export REC05_VOXEL_MODULE_PATH="${REC05_VOXEL_MODULE_PATH:-$SPLAT/dist/index.mjs}"
export REC05_VOXEL_TIMEOUT_SECONDS="${REC05_VOXEL_TIMEOUT_SECONDS:-1800}"
export PRODUCT_GEOMETRY_CONFIG="${PRODUCT_GEOMETRY_CONFIG:-/opt/real2sim/app/configs/product/geometry_indoor_v1.json}"
export PRODUCT_SCENE_RUNTIME_PYTHON="${PRODUCT_SCENE_RUNTIME_PYTHON:-$SCENE/bin/python}"
export PRODUCT_SAM2_CHECKPOINT="${PRODUCT_SAM2_CHECKPOINT:-$SCENE/checkpoints/sam2.1_hiera_tiny.pt}"
export PRODUCT_LAMA_CHECKPOINT="${PRODUCT_LAMA_CHECKPOINT:-$SCENE/weights/big-lama.pt}"
export REC04_BRUSH_LPIPS_PYTHON="${REC04_BRUSH_LPIPS_PYTHON:-$SCENE/bin/python}"
# Đề xuất tỉ lệ mét tự động (MoGe-2): chỉ bật khi image có trọng số; thiếu thì worker bỏ qua bước này.
if [ -f "$SCENE/weights/moge-2-vitb-normal.pt" ]; then
  export REC06_MOGE_PYTHON="${REC06_MOGE_PYTHON:-$SCENE/bin/python}"
  export REC06_MOGE_MODEL="${REC06_MOGE_MODEL:-$SCENE/weights/moge-2-vitb-normal.pt}"
fi
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
export REC17_LIDAR_ODOMETRY_PYTHON="${REC17_LIDAR_ODOMETRY_PYTHON:-${R2S_LIDAR_RUNTIME:-/opt/real2sim/lidar_runtime}/bin/python}"
export PRODUCT_INPUT_RUNTIME_REGISTRY="${PRODUCT_INPUT_RUNTIME_REGISTRY:-$STATE/input_runtime_registry.json}"
if ! "$PY" -m scripts.gpu.qualify_input_runtimes --out "$PRODUCT_INPUT_RUNTIME_REGISTRY"; then
  echo "[!] Không sinh được registry năng lực input; luồng nhập mới sẽ báo chưa có bộ xử lý phù hợp." >&2
  unset PRODUCT_INPUT_RUNTIME_REGISTRY
fi

mode="${1:-worker}"
[ "$#" -gt 0 ] && shift
case "$mode" in
  worker)
    exec "$PY" -m scripts.gpu.run_workers --workers "${STUDIO_WORKERS:-auto}"
    ;;
  stack)
    "$PY" -m uvicorn src.main:app --host 0.0.0.0 --port "${APP_PORT:-8000}" &
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
