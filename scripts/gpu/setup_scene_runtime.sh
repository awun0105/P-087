#!/usr/bin/env bash
# Cài runtime GPU cho tách scene theo vật (pipeline v2, ADR 0007) trên một máy mới.
#
# Runtime này tách khỏi .venv của app (RUNTIME_POLICY §2): app gọi các runner qua subprocess.
# Gồm: SAM2 (mask), gsplat (gán nhãn theo đóng góp render + vá nền), CoACD + scikit-image (collider
# phân rã lồi), usd-core (xuất USD lai), LPIPS (đo chất lượng), trọng số SAM2 và LaMa.
#
#   scripts/gpu/setup_scene_runtime.sh [thư_mục_runtime]        # mặc định: data/scene_runtime
#
# Yêu cầu máy: GPU NVIDIA + driver, CUDA toolkit có `nvcc` (gsplat biên dịch kernel lần đầu),
# header Python 3.12 (`python3.12-dev`), `uv`, `git`, `curl`. Phiên bản ghim = bản đã chạy thật trên
# Quadro T2000 (2026-10-01). Sau khi cài, đặt 3 biến in ra ở cuối vào file env của stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME="${1:-$ROOT/data/scene_runtime}"
SAM2_COMMIT="2b90b9f5ceec907a1c18123530e92e794ad901a4"
SAM2_CHECKPOINT_URL="https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt"
SAM2_CHECKPOINT_SHA="7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"
LAMA_URL="https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
LAMA_SHA="7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c"
# MoGe-2 (đề xuất tỉ lệ mét tự động, ADR 0001 §2). Ghim commit thời MoGe-2: bản main đã là MoGe-3 với
# dependency khác. Cài --no-deps để không đổi phiên bản numpy/opencv mà SAM2 và gsplat đang dùng.
MOGE_COMMIT="b942f00bdc2a2a23ebb474fbe034d487e6dcceec"
UTILS3D_COMMIT="3fab839f0be9931dac7c8488eb0e1600c236e183"
MOGE_URL="https://huggingface.co/Ruicheng/moge-2-vitb-normal/resolve/main/model.pt"
MOGE_SHA="16b8110e86d5dc5a849db120ca96ef3a223fd30b0c9146d1d81db504073da5f6"

need() { command -v "$1" >/dev/null || { echo "[!] Thiếu lệnh: $1" >&2; exit 1; }; }
need uv; need git; need curl
command -v nvcc >/dev/null || [ -x /usr/local/cuda/bin/nvcc ] || {
  echo "[!] Không thấy nvcc: gsplat cần CUDA toolkit để biên dịch kernel." >&2; exit 1; }
# Header có thể đến từ python3.12-dev hoặc từ CPATH (vd. header của một bản Python 3.12 khác trên máy).
python3.12 -c "import sysconfig, os, sys; sys.exit(0 if os.path.isfile(os.path.join(sysconfig.get_paths()['include'], 'Python.h')) else 1)" \
  || [ -f "${CPATH:-/nonexistent}/Python.h" ] || {
  echo "[!] Thiếu header Python 3.12 (Python.h). Cài: sudo apt install python3.12-dev" >&2; exit 1; }

fetch() {  # fetch <url> <đích> <sha256>
  if [ ! -f "$2" ] || [ "$(sha256sum "$2" | cut -d' ' -f1)" != "$3" ]; then
    echo "[tải] $(basename "$2")"; curl -L --fail -o "$2" "$1"
  fi
  [ "$(sha256sum "$2" | cut -d' ' -f1)" = "$3" ] || { echo "[!] Sai checksum: $2" >&2; exit 1; }
}

[ -x "$RUNTIME/bin/python" ] || uv venv --python 3.12 "$RUNTIME"
PY="$RUNTIME/bin/python"
uv pip install --python "$PY" --index-url https://download.pytorch.org/whl/cu126 \
  torch==2.7.1 torchvision==0.22.1
uv pip install --python "$PY" \
  "sam-2 @ git+https://github.com/facebookresearch/sam2@${SAM2_COMMIT}" \
  gsplat==1.5.3 coacd==1.0.14 scikit-image==0.26.0 opencv-python-headless==5.0.0.93 \
  trimesh==5.1.0 usd-core==26.8 lpips==0.1.4 rich==15.0.0 scipy==1.18.1
uv pip install --python "$PY" --no-deps \
  "moge @ git+https://github.com/microsoft/MoGe.git@${MOGE_COMMIT}" \
  "utils3d @ git+https://github.com/EasternJournalist/utils3d.git@${UTILS3D_COMMIT}"
uv pip install --python "$PY" huggingface_hub click

mkdir -p "$RUNTIME/checkpoints" "$RUNTIME/weights"
fetch "$SAM2_CHECKPOINT_URL" "$RUNTIME/checkpoints/sam2.1_hiera_tiny.pt" "$SAM2_CHECKPOINT_SHA"
fetch "$LAMA_URL" "$RUNTIME/weights/big-lama.pt" "$LAMA_SHA"
fetch "$MOGE_URL" "$RUNTIME/weights/moge-2-vitb-normal.pt" "$MOGE_SHA"
"$PY" -c "from moge.model.v2 import MoGeModel"

if [ "${R2S_SKIP_GPU_CHECK:-0}" = "1" ]; then
  # Lúc build image Docker không có GPU: chỉ kiểm import và biên dịch sẵn kernel gsplat (cần nvcc, không cần GPU).
  # Bài render thật được kiểm lại khi container chạy (`scripts/kaggle/preflight.py`).
  echo "[kiểm] import + biên dịch kernel gsplat, bỏ qua bài render GPU…"
  "$PY" - <<'PY'
import torch, coacd, skimage, cv2, trimesh  # noqa: F401
from gsplat.cuda._backend import _C
from pxr import UsdVol
from sam2.build_sam import build_sam2  # noqa: F401

assert _C is not None, "kernel gsplat không biên dịch được"
assert hasattr(UsdVol, "ParticleField3DGaussianSplat"), "usd-core thiếu schema ParticleField"
print("ok (chưa kiểm GPU): torch", torch.__version__)
PY
else
echo "[kiểm] import + biên dịch kernel gsplat (lần đầu mất vài phút)…"
"$PY" - <<'PY'
import torch, gsplat, coacd, skimage, cv2, trimesh  # noqa: F401
from pxr import UsdVol
from sam2.build_sam import build_sam2  # noqa: F401

assert torch.cuda.is_available(), "torch không thấy GPU"
assert hasattr(UsdVol, "ParticleField3DGaussianSplat"), "usd-core thiếu schema ParticleField"
device = "cuda"
means = torch.randn(1000, 3, device=device); means[:, 2] += 5
quats = torch.nn.functional.normalize(torch.randn(1000, 4, device=device), dim=-1)
image, _, _ = gsplat.rasterization(
    means, quats, torch.full((1000, 3), 0.02, device=device), torch.full((1000,), 0.8, device=device),
    torch.rand(1000, 3, device=device), torch.eye(4, device=device)[None],
    torch.tensor([[300.0, 0, 160], [0, 300.0, 120], [0, 0, 1]], device=device)[None], 320, 240, render_mode="RGB+ED",
)
print("ok: torch", torch.__version__, "· gsplat", gsplat.__version__, "· render", tuple(image.shape))
PY
fi

# LPIPS chấm ảnh giữ lại sau khi train 3DGS: tải sẵn trọng số VGG vào cache của torch để worker không cần mạng lúc
# chạy job. Tải lỗi thì bỏ qua — bảng chỉ số sẽ ghi LPIPS "chưa đo", PSNR/SSIM vẫn có.
"$PY" -c "import lpips; lpips.LPIPS(net='vgg', verbose=False)" >/dev/null 2>&1 \
  || echo "[cảnh báo] chưa tải được trọng số LPIPS-VGG; LPIPS sẽ không được chấm cho tới khi tải được."

cat <<EOF

Runtime sẵn sàng. Thêm vào file env của stack (vd scripts/gpu/studio.env):
  PRODUCT_SCENE_RUNTIME_PYTHON=$PY
  PRODUCT_SAM2_CHECKPOINT=$RUNTIME/checkpoints/sam2.1_hiera_tiny.pt
  PRODUCT_LAMA_CHECKPOINT=$RUNTIME/weights/big-lama.pt
  REC06_MOGE_PYTHON=$PY
  REC06_MOGE_MODEL=$RUNTIME/weights/moge-2-vitb-normal.pt
  REC04_BRUSH_LPIPS_PYTHON=$PY
EOF
