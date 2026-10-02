#!/usr/bin/env bash
# Sinh scripts/gpu/studio.env cho checkout **trên máy đang chạy**: mọi đường dẫn suy từ root repo, không có đường dẫn
# của máy nào viết cứng. File đã có thì giữ nguyên (FORCE_ENV=1 để sinh lại; bản cũ được sao lưu cạnh nó).
#
#   scripts/studio/make_env.sh [đường dẫn file env]
#
# File sinh ra chỉ cấu hình đường dẫn và lựa chọn mặc định; nó không cài runtime và không chứa secret
# (API key nằm ở .env gốc repo).
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
target="${1:-$root/scripts/gpu/studio.env}"
runtime="$root/data/rec04_runtime"
scene="$root/data/scene_runtime"

if [ -f "$target" ] && [ "${FORCE_ENV:-0}" != "1" ]; then
  echo "[env] giữ nguyên $target (FORCE_ENV=1 để sinh lại)."
  exit 0
fi
[ -f "$target" ] && cp "$target" "$target.bak-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$(dirname "$target")"

# Brush train qua Vulkan: chỉ định ICD NVIDIA (nếu có) để không rơi về GPU tích hợp hoặc CPU.
icd=""
for candidate in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do
  [ -f "$candidate" ] && { icd="$candidate"; break; }
done
brush_env='{"RUST_LOG":"info,wgpu_core=warn"}'
[ -n "$icd" ] && brush_env="{\"RUST_LOG\":\"info,wgpu_core=warn\",\"VK_ICD_FILENAMES\":\"$icd\"}"

{
  cat <<EOF
# Sinh tự động bởi scripts/studio/make_env.sh cho checkout ở $root.
APP_ENV=development
DATABASE_URL='sqlite:///$root/data/studio_local/runtime.db'
ARTIFACT_ROOT='$root/data/studio_local/artifacts'
PRODUCT_WORKER_ROOT='$root/data/studio_local/workers'
# Máy cá nhân của teammate: không bắt đăng nhập. Đặt true rồi tạo tài khoản bằng \`make -f Makefile.studio account\`.
AUTH_REQUIRED=${AUTH_REQUIRED:-false}
# MVP: người upload tự xác nhận không có khuôn mặt/biển số (xem ADR 0002).
PRODUCT_PRIVACY_MODE=self_attested
PRODUCT_UPLOAD_MAX_BYTES=4294967296
PRODUCT_PROCESSING_CONFIG='$root/configs/product/processing_presets_v1.json'
PRODUCT_GEOMETRY_CONFIG='$root/configs/product/geometry_v1.json'
PRODUCT_RUNTIME_MANIFEST='$root/data/studio_local/runtime_manifest.json'
PRODUCT_RERUN_RECORDING_DIR='$root/data/rerun_recordings'
# Thư viện video mẫu: mỗi thư mục con là một bundle đã xử lý sẵn.
PRODUCT_DEMO_DIR='${DEMO_DIR:-$root/data/demo/library}'

# ── Runtime xử lý (cài bằng scripts/studio/bootstrap.sh; thiếu thì Studio chạy ở chế độ chỉ xem) ──
REC03_COLMAP_COMMAND='["sh","$runtime/colmap-launcher.sh"]'
REC03_COLMAP_RUNTIME_IDENTITY=colmap-image-sha256:b8498ebecab11c3f9b9a25370e3fcfb6de9b6bcd4f3c85d5dc39a40229f40954
REC03_COLMAP_TIMEOUT_SECONDS=3600
REC04_BRUSH_COMMAND='["$runtime/brush/brush-app-x86_64-unknown-linux-gnu/brush_app"]'
REC04_BRUSH_EXPECTED_VERSION=0.3.0
REC04_BRUSH_RUNTIME_IDENTITY=brush-v0.3.0-linux-archive-sha256:4f0f9a8785d1951c62df26aae247c02c5bba32b00f40b06df4e1c9b867399e20
REC04_BRUSH_ENVIRONMENT='$brush_env'
REC04_BRUSH_TIMEOUT_SECONDS=3600
REC04_SPLAT_MODULE_PATH='$runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs'
REC04_SPLAT_DEVICE=gpu
REC05_VOXEL_CLI='$runtime/node_modules/@playcanvas/splat-transform/bin/cli.mjs'
REC05_VOXEL_MODULE_PATH='$runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs'
REC05_VOXEL_TIMEOUT_SECONDS=1800
# Máy có GPU tích hợp + GPU rời: nếu bước nén SOG/voxel chọn nhầm GPU, đặt chỉ số adapter của GPU rời ở đây.
# PRODUCT_GEOMETRY_GPU_INDEX=1
EOF
  if [ -x "$scene/bin/python" ]; then
    cat <<EOF

# ── Runtime tách vật thể, đề xuất tỉ lệ mét, LPIPS (scripts/gpu/setup_scene_runtime.sh data/scene_runtime) ──
PRODUCT_SCENE_RUNTIME_PYTHON='$scene/bin/python'
PRODUCT_SAM2_CHECKPOINT='$scene/checkpoints/sam2.1_hiera_tiny.pt'
PRODUCT_LAMA_CHECKPOINT='$scene/weights/big-lama.pt'
REC04_BRUSH_LPIPS_PYTHON='$scene/bin/python'
EOF
    if [ -f "$scene/weights/moge-2-vitb-normal.pt" ]; then
      printf "REC06_MOGE_PYTHON='%s'\nREC06_MOGE_MODEL='%s'\n" "$scene/bin/python" "$scene/weights/moge-2-vitb-normal.pt"
    fi
  else
    printf '\n# Chưa có runtime tách vật thể (data/scene_runtime): job vẫn chạy, bước tách vật lùi về hộp ứng viên.\n'
  fi
  printf '# LLM_PROVIDER/OPENAI_API_KEY lấy từ .env ở root repo (Settings đọc .env); không ghi key vào đây.\n'
} > "$target"
echo "[env] đã sinh $target"
