#!/usr/bin/env bash
# Cài đặt toàn bộ scene runtime (SAM2, gsplat, MoGe-2, LaMa, CoACD, usd-core, Rerun) trên Colab.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE="${1:-/content/r2s}"
RUNTIME="$STATE/scene_runtime"
ENV_FILE="$STATE/colab.env"

SAM2_COMMIT="2b90b9f5ceec907a1c18123530e92e794ad901a4"
SAM2_CHECKPOINT_URL="https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt"
SAM2_CHECKPOINT_SHA="7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"

LAMA_URL="https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
LAMA_SHA="7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c"

MOGE_COMMIT="b942f00bdc2a2a23ebb474fbe034d487e6dcceec"
UTILS3D_COMMIT="3fab839f0be9931dac7c8488eb0e1600c236e183"
MOGE_URL="https://huggingface.co/Ruicheng/moge-2-vitb-normal/resolve/main/model.pt"
MOGE_SHA="16b8110e86d5dc5a849db120ca96ef3a223fd30b0c9146d1d81db504073da5f6"

export PATH="/usr/local/cuda/bin:$PATH"

fetch() {
  if [ ! -f "$2" ] || [ "$(sha256sum "$2" | cut -d' ' -f1)" != "$3" ]; then
    echo "[tải] $(basename "$2")"
    curl -L --fail -o "$2" "$1"
  fi
  [ "$(sha256sum "$2" | cut -d' ' -f1)" = "$3" ] || { echo "[!] Sai checksum: $2" >&2; exit 1; }
}

echo "[1/5] Khởi tạo venv scene_runtime..."
[ -x "$RUNTIME/bin/python" ] || uv venv --python 3.12 "$RUNTIME"
PY="$RUNTIME/bin/python"

echo "[2/5] Cài PyTorch (CUDA 12.6)..."
uv pip install --python "$PY" --index-url https://download.pytorch.org/whl/cu126 \
  torch==2.7.1 torchvision==0.22.1

echo "[3/5] Cài SAM2, gsplat, CoACD, usd-core, lpips, Rerun..."
uv pip install --python "$PY" \
  "sam-2 @ git+https://github.com/facebookresearch/sam2@${SAM2_COMMIT}" \
  gsplat==1.5.3 coacd==1.0.14 scikit-image==0.26.0 opencv-python-headless==5.0.0.93 \
  trimesh==5.1.0 usd-core==26.8 lpips==0.1.4 rich==15.0.0 scipy==1.18.1 rerun-sdk huggingface_hub click

echo "[4/5] Cài MoGe-2 và utils3d..."
uv pip install --python "$PY" --no-deps \
  "moge @ git+https://github.com/microsoft/MoGe.git@${MOGE_COMMIT}" \
  "utils3d @ git+https://github.com/EasternJournalist/utils3d.git@${UTILS3D_COMMIT}"

echo "[5/5] Tải checkpoints (SAM2, LaMa, MoGe-2)..."
mkdir -p "$RUNTIME/checkpoints" "$RUNTIME/weights"
fetch "$SAM2_CHECKPOINT_URL" "$RUNTIME/checkpoints/sam2.1_hiera_tiny.pt" "$SAM2_CHECKPOINT_SHA"
fetch "$LAMA_URL" "$RUNTIME/weights/big-lama.pt" "$LAMA_SHA"
fetch "$MOGE_URL" "$RUNTIME/weights/moge-2-vitb-normal.pt" "$MOGE_SHA"

echo "[kiểm tra] Kiểm tra import MoGe..."
"$PY" -c "from moge.model.v2 import MoGeModel; print('MoGe OK!')"

echo "[kiểm tra] Kiểm tra gsplat rasterization trên GPU..."
"$PY" - <<'PY'
import torch, gsplat, coacd, skimage, cv2, trimesh
from pxr import UsdVol
from sam2.build_sam import build_sam2

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
print("ok: torch", torch.__version__, "· gsplat", gsplat.__version__, "· render shape", tuple(image.shape))
PY

echo "[cập nhật] Ghi biến môi trường vào $ENV_FILE..."
cat >> "$ENV_FILE" <<EOF
PRODUCT_SCENE_RUNTIME_PYTHON=$PY
PRODUCT_SAM2_CHECKPOINT=$RUNTIME/checkpoints/sam2.1_hiera_tiny.pt
PRODUCT_LAMA_CHECKPOINT=$RUNTIME/weights/big-lama.pt
REC06_MOGE_PYTHON=$PY
REC06_MOGE_MODEL=$RUNTIME/weights/moge-2-vitb-normal.pt
REC04_BRUSH_LPIPS_PYTHON=$PY
EOF

echo "[cập nhật] Tạo lại runtime manifest..."
set -a; source "$ENV_FILE"; set +a
.venv/bin/python -m scripts.gpu.make_runtime_manifest --out "$PRODUCT_RUNTIME_MANIFEST"

echo "=== Toàn bộ Scene Runtime (SAM2, MoGe, LaMa, gsplat, CoACD, Rerun) đã sẵn sàng! ==="
