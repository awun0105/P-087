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
export REPO="$ROOT"
source "$ROOT/scripts/gpu/install.d/_lib.sh"
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
# EgoBlur Gen2 (che khuôn mặt/biển số, AUD-18; Apache-2.0). Trọng số chỉ tải được từ
# https://www.projectaria.com/tools/egoblur/ sau khi nhập email và đồng ý giấy phép, nên script không tự tải:
# đặt R2S_EGOBLUR_WEIGHTS trỏ tới thư mục chứa hai file .jit đã tải. Không đặt thì bước ẩn danh không dùng được.
EGOBLUR_FACE_SHA="2ba183ff74a66752f6457846efb4379b351727d1c9eaef461ed4be8db18cc2e8"
EGOBLUR_LP_SHA="1d6b3fc37fce4158d3b7d4a364290cfeeccc86a9cd84a376c443d560f11497f4"

need() { command -v "$1" >/dev/null || { echo "[!] Thiếu lệnh: $1" >&2; exit 1; }; }
need uv; need git; need curl
command -v nvcc >/dev/null || [ -x /usr/local/cuda/bin/nvcc ] || {
  echo "[!] Không thấy nvcc: gsplat cần CUDA toolkit để biên dịch kernel." >&2; exit 1; }
[ -x "$RUNTIME/bin/python" ] || uv venv --python 3.12.14 "$RUNTIME"
PY="$RUNTIME/bin/python"
# gsplat biên dịch kernel với header của chính Python venv này (bản uv quản lý có sẵn Python.h). Đặt CPATH ở đây,
# không nhận từ ngoài, để không lẫn header của Python khác (ObjectGS dùng 3.8).
PY_INCLUDE="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["include"])')"
[ -f "$PY_INCLUDE/Python.h" ] || {
  echo "[!] Thiếu header Python 3.12 (Python.h) tại $PY_INCLUDE. Cài: sudo apt install python3.12-dev" >&2; exit 1; }
export CPATH="$PY_INCLUDE"
uv pip install --python "$PY" --index-url https://download.pytorch.org/whl/cu126 \
  torch==2.7.1 torchvision==0.22.1
uv pip install --python "$PY" \
  "sam-2 @ git+https://github.com/facebookresearch/sam2@${SAM2_COMMIT}" \
  gsplat==1.5.3 coacd==1.0.14 scikit-image==0.26.0 opencv-python-headless==5.0.0.93 \
  trimesh==5.1.0 usd-core==26.8 lpips==0.1.4 rich==15.0.0 scipy==1.18.1
uv pip install --python "$PY" --no-deps \
  "moge @ git+https://github.com/microsoft/MoGe.git@${MOGE_COMMIT}" \
  "utils3d @ git+https://github.com/EasternJournalist/utils3d.git@${UTILS3D_COMMIT}"
uv pip install --python "$PY" huggingface_hub==2.1.1 click==8.5.0
# Gói egoblur ghim torch 2.9.1 và kéo moviepy/av/vrs; chỉ cần phần detector nên cài --no-deps. Hai model đã
# chạy trên torch 2.7.1 của runtime này (kiểm 2026-10-09).
uv pip install --python "$PY" --no-deps egoblur==2.0.1

mkdir -p "$RUNTIME/checkpoints" "$RUNTIME/weights"
fetch "$SAM2_CHECKPOINT_URL" "$RUNTIME/checkpoints/sam2.1_hiera_tiny.pt" "$SAM2_CHECKPOINT_SHA"
fetch "$LAMA_URL" "$RUNTIME/weights/big-lama.pt" "$LAMA_SHA"
fetch "$MOGE_URL" "$RUNTIME/weights/moge-2-vitb-normal.pt" "$MOGE_SHA"
"$PY" -c "from moge.model.v2 import MoGeModel"
if [ -n "${R2S_EGOBLUR_WEIGHTS:-}" ]; then
  for pair in "ego_blur_face_gen2.jit:$EGOBLUR_FACE_SHA" "ego_blur_lp_gen2.jit:$EGOBLUR_LP_SHA"; do
    name="${pair%%:*}"
    [ -f "$RUNTIME/weights/$name" ] || cp "$R2S_EGOBLUR_WEIGHTS/$name" "$RUNTIME/weights/$name"
    [ "$(sha256sum "$RUNTIME/weights/$name" | cut -d' ' -f1)" = "${pair##*:}" ] \
      || { echo "[!] Sai checksum: $RUNTIME/weights/$name" >&2; exit 1; }
  done
else
  echo "[bỏ qua] EgoBlur: chưa đặt R2S_EGOBLUR_WEIGHTS, bước ẩn danh khuôn mặt/biển số sẽ không dùng được."
fi

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
# chạy job. Không phát hành image thiếu trọng số rồi mới tải lúc đang xử lý scene.
"$PY" -c "import lpips; lpips.LPIPS(net='vgg', verbose=False)"
uv pip freeze --python "$PY" > "$RUNTIME/installed.txt"

cat <<EOF

Runtime sẵn sàng. Thêm vào file env của stack (vd scripts/gpu/studio.env):
  PRODUCT_SCENE_RUNTIME_PYTHON=$PY
  PRODUCT_SAM2_CHECKPOINT=$RUNTIME/checkpoints/sam2.1_hiera_tiny.pt
  PRODUCT_LAMA_CHECKPOINT=$RUNTIME/weights/big-lama.pt
  R2S_MOGE_PYTHON=$PY
  R2S_MOGE_MODEL=$RUNTIME/weights/moge-2-vitb-normal.pt
  R2S_BRUSH_LPIPS_PYTHON=$PY
EOF
