#!/usr/bin/env bash
# Dựng runtime ObjectGS (tách vật thể bằng 3DGS có nhãn) ở một thư mục đích, chạy lại được.
#
#   scripts/gpu/setup_objectgs_runtime.sh <thư_mục_đích> [--wheels <thư_mục_wheel>] [--skip-gpu-check]
#   scripts/gpu/setup_objectgs_runtime.sh <thư_mục_đích> --print-plan     # chỉ in commit ghim và danh sách, không cài
#
# Bố cục đích (giống laptop để code không phải đổi): python/, cuda/, ObjectGS/, gsplat-object/, glm/,
# torch_extensions/ (cache biên dịch gsplat dựng sẵn ở bước cuối). Commit ghim đọc từ
# src/services/scene/objectgs.py, không chép tay. Cuối script in các biến PRODUCT_OBJECTGS_* để dán vào env.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LISTS="$ROOT/configs/runtime/objectgs"

# micromamba: bản ghim nằm ở configs/runtime/pins.env (một nguồn cho mọi runtime GPU). Chi tiết nguồn và checksum ở đó.
pins_value() { sed -n "s/^$1=\(.*\)\$/\1/p" "$ROOT/configs/runtime/pins.env" | head -n1; }
MICROMAMBA_URL="$(pins_value MICROMAMBA_URL)"
MICROMAMBA_SHA="$(pins_value MICROMAMBA_SHA)"
MICROMAMBA_BIN_SHA="$(pins_value MICROMAMBA_BIN_SHA)"
[ -n "$MICROMAMBA_URL" ] && [ -n "$MICROMAMBA_SHA" ] && [ -n "$MICROMAMBA_BIN_SHA" ] \
  || die "thiếu MICROMAMBA_* trong configs/runtime/pins.env"
OBJECTGS_REPO="https://github.com/RuijieZhu94/ObjectGS.git"
GSPLAT_REPO="https://github.com/RuijieZhu94/gsplat-object.git"
GLM_REPO="https://github.com/g-truc/glm.git"
TORCH_INDEX="https://download.pytorch.org/whl/cu118"
PYG_INDEX="https://data.pyg.org/whl/torch-2.1.2+cu118.html"

need() { command -v "$1" >/dev/null || { echo "[!] Thiếu lệnh: $1" >&2; exit 1; }; }
die() { echo "[!] $*" >&2; exit 1; }
sha_of() { sha256sum "$1" | cut -d' ' -f1; }

# Commit ghim: một nguồn duy nhất là src/services/scene/objectgs.py.
pinned() {
  local value
  value="$(sed -n "s/^$1 = \"\([0-9a-f]\{40\}\)\"$/\1/p" "$ROOT/src/services/scene/objectgs.py")"
  [ -n "$value" ] || die "không đọc được $1 từ src/services/scene/objectgs.py"
  printf '%s' "$value"
}
OBJECTGS_COMMIT="$(pinned OBJECTGS_COMMIT)"
GSPLAT_COMMIT="$(pinned GSPLAT_COMMIT)"
GLM_COMMIT="$(pinned GLM_COMMIT)"

# Danh sách gói đọc trực tiếp từ configs/runtime/objectgs (dữ liệu chép từ laptop đang chạy).
specs() { grep -v '^#' "$LISTS/$1" | grep . || true; }
PY_SPECS="$(specs conda-python.txt)"
CUDA_SPECS="$(specs conda-cuda.txt)"
TORCH_PINS="$(specs torch.txt | grep -v '^torch-scatter' || true)"
SCATTER_PIN="$(specs torch.txt | grep '^torch-scatter' || true)"
[ -n "$PY_SPECS" ] && [ -n "$CUDA_SPECS" ] && [ -n "$TORCH_PINS" ] && [ -n "$SCATTER_PIN" ] \
  || die "thiếu danh sách trong configs/runtime/objectgs"
[ "$(grep -c '==' "$LISTS/requirements.lock.txt")" -gt 0 ] || die "requirements.lock.txt trống"

DEST=""
WHEELS=""
SKIP_GPU_CHECK=0
PRINT_PLAN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --wheels) WHEELS="${2:?--wheels cần thư mục}"; shift 2 ;;
    --skip-gpu-check) SKIP_GPU_CHECK=1; shift ;;
    --print-plan) PRINT_PLAN=1; shift ;;
    -*) die "tham số lạ: $1" ;;
    *) [ -z "$DEST" ] || die "chỉ nhận một thư mục đích"; DEST="$1"; shift ;;
  esac
done
[ -n "$DEST" ] || die "dùng: $0 <thư_mục_đích> [--wheels <dir>] [--skip-gpu-check] [--print-plan]"

if [ "$PRINT_PLAN" = 1 ]; then
  echo "OBJECTGS_COMMIT=$OBJECTGS_COMMIT"
  echo "GSPLAT_COMMIT=$GSPLAT_COMMIT"
  echo "GLM_COMMIT=$GLM_COMMIT"
  echo "python: $(echo "$PY_SPECS" | tr '\n' ' ')"
  echo "cuda: $(echo "$CUDA_SPECS" | tr '\n' ' ')"
  echo "torch: $(echo "$TORCH_PINS" | tr '\n' ' ') $SCATTER_PIN"
  echo "pip lock: $(grep -c '==' "$LISTS/requirements.lock.txt") gói"
  exit 0
fi

# Thư mục đích đã có nội dung mà không có dấu của script này: không cài đè lên, dừng trước mọi bước tải.
if [ -d "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ] && [ ! -f "$DEST/.r2s-installed" ]; then
  die "thư mục đích $DEST đã có nội dung nhưng không có .r2s-installed (không phải lần dựng của script này). \
Chọn một thư mục rỗng khác, hoặc xoá nội dung cũ bằng tay rồi chạy lại. Script không tự xoá gì."
fi

need git; need curl; need tar; need sha256sum
if [ "$SKIP_GPU_CHECK" = 0 ]; then
  command -v nvidia-smi >/dev/null || die "không thấy nvidia-smi; dùng --skip-gpu-check để dựng không cần GPU"
fi

mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"
PY="$DEST/python/bin/python"
CXX_BIN="$DEST/cuda/bin/x86_64-conda-linux-gnu-g++"
TMP="$DEST/.tmp"
MAMBA_ROOT="$DEST/.mamba"
trap 'rm -rf "$TMP"' EXIT

# Dấu đã cài: cùng công thức + cùng commit + cùng danh sách thì thoát ngay.
RECIPE="objectgs-runtime-1 $OBJECTGS_COMMIT $GSPLAT_COMMIT $GLM_COMMIT $(cd "$LISTS" && sha256sum requirements.lock.txt torch.txt conda-python.txt conda-cuda.txt | cut -d' ' -f1 | tr '\n' ' ')"
STAMP="$DEST/.r2s-installed"
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$RECIPE" ]; then
  echo "[bỏ qua] đã cài đúng công thức này ở $DEST"
else
  mkdir -p "$TMP"
  fetch() {  # fetch <url> <đích> <sha256>: tải lại nếu thiếu hoặc sai checksum, dừng nếu checksum vẫn sai
    if [ ! -f "$2" ] || [ "$(sha_of "$2")" != "$3" ]; then
      echo "[tải] $(basename "$2")"; curl -L --fail -o "$2" "$1"
    fi
    [ "$(sha_of "$2")" = "$3" ] || die "sai checksum: $2"
  }

  if [ ! -x "$TMP/bin/micromamba" ]; then
    fetch "$MICROMAMBA_URL" "$TMP/micromamba.tar.bz2" "$MICROMAMBA_SHA"
    tar -xjf "$TMP/micromamba.tar.bz2" -C "$TMP" bin/micromamba
  fi
  [ "$(sha_of "$TMP/bin/micromamba")" = "$MICROMAMBA_BIN_SHA" ] || die "sai checksum binary micromamba: $TMP/bin/micromamba"
  MM="$TMP/bin/micromamba"
  export MAMBA_ROOT_PREFIX="$MAMBA_ROOT"

  if [ ! -x "$PY" ]; then
    # shellcheck disable=SC2086
    "$MM" create -y -p "$DEST/python" -c conda-forge $PY_SPECS
  fi
  if [ ! -x "$CXX_BIN" ]; then
    # shellcheck disable=SC2086
    "$MM" create -y -p "$DEST/cuda" --override-channels -c conda-forge -c nvidia $CUDA_SPECS
  fi

  # Torch: index cu118 (hoặc thư mục wheel khi cài offline), rồi PyG, rồi danh sách khoá.
  if [ -n "$WHEELS" ]; then
    [ -d "$WHEELS" ] || die "không thấy thư mục wheel: $WHEELS"
    OFFLINE=(--no-index --find-links "$WHEELS")
    # shellcheck disable=SC2086
    "$PY" -m pip install $TORCH_PINS "${OFFLINE[@]}"
    "$PY" -m pip install "$(echo "$SCATTER_PIN")" "${OFFLINE[@]}"
  else
    # shellcheck disable=SC2086
    "$PY" -m pip install $TORCH_PINS --index-url "$TORCH_INDEX"
    "$PY" -m pip install "$SCATTER_PIN" --find-links "$PYG_INDEX"
    OFFLINE=()
  fi
  # Mỗi gói trong khoá có sha256 của đúng file wheel/sdist trên laptop; file khác (kể cả cùng phiên bản) bị từ chối.
  "$PY" -m pip install --require-hashes -r "$LISTS/requirements.lock.txt" "${OFFLINE[@]}"

  checkout() {  # checkout <url> <thư mục> <commit>: detach đúng commit, cây sạch
    local dir="$2" commit="$3"
    [ -d "$dir/.git" ] || git clone --quiet "$1" "$dir"
    git -C "$dir" cat-file -e "$commit^{commit}" 2>/dev/null || git -C "$dir" fetch --quiet origin
    git -C "$dir" checkout --quiet --detach "$commit"
    [ -z "$(git -C "$dir" status --porcelain)" ] || die "$dir có thay đổi chưa commit; không dùng được"
    [ "$(git -C "$dir" rev-parse HEAD)" = "$commit" ] || die "$dir không ở đúng commit $commit"
  }
  checkout "$OBJECTGS_REPO" "$DEST/ObjectGS" "$OBJECTGS_COMMIT"
  checkout "$GSPLAT_REPO" "$DEST/gsplat-object" "$GSPLAT_COMMIT"
  checkout "$GLM_REPO" "$DEST/glm" "$GLM_COMMIT"

  # Dựng sẵn extension gsplat: import _backend là lúc JIT biên dịch, với đúng biến như objectgs.py.
  mkdir -p "$DEST/torch_extensions"
  echo "[biên dịch] gsplat-object (lần đầu mất vài phút)…"
  PYTHONPATH="$DEST/gsplat-object" \
  TORCH_EXTENSIONS_DIR="$DEST/torch_extensions" \
  CUDA_HOME="$DEST/cuda" \
  PATH="$DEST/cuda/bin:$PATH" \
  CXX="$CXX_BIN" CC="$CXX_BIN" \
  CPLUS_INCLUDE_PATH="$DEST/python/include:$DEST/glm" \
  MAX_JOBS="${MAX_JOBS:-2}" \
  TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-7.5;8.0;8.6;8.9}" \
  "$PY" -c "import gsplat.cuda._backend as backend; assert backend._C is not None, 'extension không biên dịch được'; print('ok: gsplat extension')"

  rm -rf "$TMP"
  printf '%s' "$RECIPE" > "$STAMP"
fi

cat <<EOF

Runtime ObjectGS sẵn sàng. Dán vào file env của stack (scripts/gpu/studio.env):
PRODUCT_OBJECTGS_RUNTIME_PYTHON=$PY
PRODUCT_OBJECTGS_REPOSITORY=$DEST/ObjectGS
PRODUCT_OBJECTGS_GSPLAT_REPOSITORY=$DEST/gsplat-object
PRODUCT_OBJECTGS_CUDA_HOME=$DEST/cuda
PRODUCT_OBJECTGS_CXX=$CXX_BIN
PRODUCT_OBJECTGS_GLM_REPOSITORY=$DEST/glm
PRODUCT_OBJECTGS_EXTENSION_CACHE_DIR=$DEST/torch_extensions
EOF
