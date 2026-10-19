#!/usr/bin/env bash
# Hàm dùng chung của install.sh, install.d/*.sh và doctor.sh. File này được source, không chạy trực tiếp.
#
# Quy ước: mọi phiên bản đọc từ configs/runtime/pins.env (pin); mọi tải về đi qua fetch() có kiểm sha256; mọi công cụ
# có verify_<tên> (đã có và đúng phiên bản thì không cài lại) và install_<tên>.

REPO="${REPO:?REPO chưa đặt}"
PINS="$REPO/configs/runtime/pins.env"

die() { echo "[!] $*" >&2; exit 1; }

# pin KHOA: đọc đúng một khoá từ pins.env (không source file, không eval).
pin() {
  local value
  value="$(sed -n "s/^$1=\(.*\)\$/\1/p" "$PINS" | head -n1)"
  [ -n "$value" ] || die "thiếu $1 trong configs/runtime/pins.env"
  printf '%s' "$value"
}

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

# py_bin: Python của repo (.venv) nếu có, không thì python3 hệ thống.
py_bin() { if [ -x "$REPO/.venv/bin/python" ]; then printf '%s' "$REPO/.venv/bin/python"; else command -v python3; fi; }

# fetch URL ĐÍCH SHA256: tải nếu thiếu hoặc sai checksum; dừng nếu checksum vẫn sai. Đây là nơi duy nhất gọi curl.
fetch() {
  if [ ! -f "$2" ] || [ "$(sha_of "$2")" != "$3" ]; then
    echo "[tải] $(basename "$2")"
    local partial
    partial="$(mktemp "$2.download.XXXXXX")"
    if ! curl -L --fail --retry 4 --retry-delay 2 --connect-timeout 30 -o "$partial" "$1"; then
      rm -f "$partial"
      die "không tải được $(basename "$2")"
    fi
    if [ "$(sha_of "$partial")" != "$3" ]; then
      rm -f "$partial"
      die "sai checksum: $2"
    fi
    mv "$partial" "$2"
  fi
  [ "$(sha_of "$2")" = "$3" ] || die "sai checksum: $2"
}

# Thư mục đích và bố cục (đặt bởi install.sh qua layout).
layout() {
  RECON="$GOC/reconstruction_runtime"
  LIDAR="$GOC/lidar_odometry_runtime"
  SCENE="$GOC/scene_runtime"
  OBJGS="$GOC/objectgs_runtime"
  COLMAP_LAUNCHER="$RECON/colmap-launcher.sh"
  COLMAP_BINARY_WRAPPER="$GOC/colmap/bin/colmap-run"
  BRUSH_BIN="$RECON/brush/brush-app-x86_64-unknown-linux-gnu/brush_app"
  NODE_BIN="$RECON/node/bin/node"
  SPLAT_DIR="$RECON/node_modules/@playcanvas/splat-transform"
  SPLAT_MODULE="$SPLAT_DIR/dist/index.mjs"
  VOXEL_CLI="$SPLAT_DIR/bin/cli.mjs"
}

# Dấu công thức: thư mục GOC/.r2s-installed/<tên>. Khớp công thức + kiểm lại thì bỏ qua.
stamp_path() { printf '%s' "$GOC/.r2s-installed/$1"; }
stamp_ok() { [ -f "$(stamp_path "$1")" ] && [ "$(cat "$(stamp_path "$1")")" = "$2" ]; }
write_stamp() {
  mkdir -p "$GOC/.r2s-installed"
  printf '%s' "$2" > "$(stamp_path "$1")"
}

# load_runtime_env FILE: đặt các biến CHƯA có (hoặc rỗng) trong môi trường. Không eval: giá trị đọc nguyên văn.
# Biến rỗng coi như chưa có: compose để trống để runtime.env của image quyết định, không lấy đường dẫn từ máy host.
load_runtime_env() {
  [ -f "$1" ] || return 0
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"
    value="${line#*=}"
    [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] || die "tên biến lạ trong $1: $key"
    if [ -z "${!key:-}" ]; then export "$key=$value"; fi
  done < "$1"
}

# Danh sách biến mà runtime.env được phép có: đường dẫn và định danh runtime, không có secret, DATABASE_URL, hay dữ liệu.
# Timeout là chính sách vận hành (scripts/gpu/studio.env.example), không đặt ở đây.
RUNTIME_ENV_ALLOWED="R2S_COLMAP_COMMAND R2S_COLMAP_RUNTIME_IDENTITY
R2S_BRUSH_COMMAND R2S_BRUSH_EXPECTED_VERSION R2S_BRUSH_ENVIRONMENT R2S_BRUSH_RUNTIME_IDENTITY
R2S_BRUSH_LPIPS_PYTHON R2S_SPLAT_DEVICE R2S_SPLAT_MODULE_PATH R2S_VOXEL_CLI R2S_VOXEL_MODULE_PATH R2S_NODE_BIN_DIR
R2S_MOGE_PYTHON R2S_MOGE_MODEL R2S_LIDAR_ODOMETRY_PYTHON
PRODUCT_SCENE_RUNTIME_PYTHON PRODUCT_SAM2_CHECKPOINT PRODUCT_LAMA_CHECKPOINT
PRODUCT_OBJECTGS_RUNTIME_PYTHON PRODUCT_OBJECTGS_REPOSITORY PRODUCT_OBJECTGS_GSPLAT_REPOSITORY PRODUCT_OBJECTGS_CUDA_HOME
PRODUCT_OBJECTGS_CXX PRODUCT_OBJECTGS_GLM_REPOSITORY PRODUCT_OBJECTGS_EXTENSION_CACHE_DIR"

# write_runtime_env FILE THÀNH_PHẦN...: ghi FILE (qua file tạm rồi mv) chỉ các biến của những thành phần đã có.
# Giá trị một dòng, không dấu nháy: load_runtime_env đọc nguyên văn nên không cần escape.
write_runtime_env() {
  local out="$1"; shift
  local tmp="$out.tmp" has c
  has() { printf '%s\n' "$@" | grep -qx "$1"; }
  : > "$tmp"
  put() { printf '%s=%s\n' "$1" "$2" >> "$tmp"; }
  if has colmap "$@"; then
    if [ "$COLMAP_MODE" = binary ]; then put R2S_COLMAP_COMMAND "[\"$COLMAP_BINARY_WRAPPER\"]"
    else put R2S_COLMAP_COMMAND "[\"sh\",\"$COLMAP_LAUNCHER\"]"; fi
    put R2S_COLMAP_RUNTIME_IDENTITY "colmap-image-$(pin COLMAP_IMAGE | sed 's/.*@//')"
  fi
  if has brush "$@"; then
    put R2S_BRUSH_COMMAND "[\"$BRUSH_BIN\"]"
    put R2S_BRUSH_EXPECTED_VERSION "$(pin BRUSH_VERSION)"
    put R2S_BRUSH_ENVIRONMENT '{"RUST_LOG":"info,wgpu_core=warn","VK_ICD_FILENAMES":"/usr/share/vulkan/icd.d/nvidia_icd.json"}'
    put R2S_BRUSH_RUNTIME_IDENTITY "brush-v$(pin BRUSH_VERSION)-linux-archive-sha256:$(pin BRUSH_SHA)"
  fi
  if has splat "$@"; then
    put R2S_SPLAT_DEVICE gpu
    put R2S_SPLAT_MODULE_PATH "$SPLAT_MODULE"
    put R2S_VOXEL_CLI "$VOXEL_CLI"
    put R2S_VOXEL_MODULE_PATH "$SPLAT_MODULE"
    # Node do ta cài (không phải --system-node): app gọi `node` từ PATH nên container cần thư mục bin của nó.
    if [ -x "$NODE_BIN" ]; then put R2S_NODE_BIN_DIR "$(dirname "$NODE_BIN")"; fi
  fi
  if has lidar_odometry "$@"; then
    put R2S_LIDAR_ODOMETRY_PYTHON "$LIDAR/bin/python"
  fi
  if has scene "$@"; then
    put PRODUCT_SCENE_RUNTIME_PYTHON "$SCENE/bin/python"
    put PRODUCT_SAM2_CHECKPOINT "$SCENE/checkpoints/sam2.1_hiera_tiny.pt"
    put PRODUCT_LAMA_CHECKPOINT "$SCENE/weights/big-lama.pt"
    put R2S_BRUSH_LPIPS_PYTHON "$SCENE/bin/python"
    if [ -f "$SCENE/weights/moge-2-vitb-normal.pt" ]; then
      put R2S_MOGE_PYTHON "$SCENE/bin/python"
      put R2S_MOGE_MODEL "$SCENE/weights/moge-2-vitb-normal.pt"
    fi
  fi
  if has objectgs "$@"; then
    put PRODUCT_OBJECTGS_RUNTIME_PYTHON "$OBJGS/python/bin/python"
    put PRODUCT_OBJECTGS_REPOSITORY "$OBJGS/ObjectGS"
    put PRODUCT_OBJECTGS_GSPLAT_REPOSITORY "$OBJGS/gsplat-object"
    put PRODUCT_OBJECTGS_CUDA_HOME "$OBJGS/cuda"
    put PRODUCT_OBJECTGS_CXX "$OBJGS/cuda/bin/x86_64-conda-linux-gnu-g++"
    put PRODUCT_OBJECTGS_GLM_REPOSITORY "$OBJGS/glm"
    put PRODUCT_OBJECTGS_EXTENSION_CACHE_DIR "$OBJGS/torch_extensions"
  fi
  # Lần chạy chỉ có một phần thành phần (--only) không được xoá dòng của thành phần khác đã ghi trước đó.
  if [ -f "$out" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      grep -q "^${line%%=*}=" "$tmp" || printf '%s\n' "$line" >> "$tmp"
    done < "$out"
  fi
  mv "$tmp" "$out"
}
