#!/usr/bin/env bash
# Runtime tách theo vật (SAM2, gsplat, CoACD, LaMa, MoGe): việc cài thuộc scripts/gpu/setup_scene_runtime.sh.
recipe_scene() { echo "scene $(sha_of "$REPO/scripts/gpu/setup_scene_runtime.sh")"; }

verify_scene() {
  [ -x "$SCENE/bin/python" ] || return 1
  local pair name key expected
  for pair in checkpoints/sam2.1_hiera_tiny.pt:SAM2_CHECKPOINT_SHA weights/big-lama.pt:LAMA_SHA weights/moge-2-vitb-normal.pt:MOGE_SHA; do
    name="${pair%%:*}"; key="${pair##*:}"
    expected="$(sed -n "s/^$key=\"\([^\"]*\)\"$/\1/p" "$REPO/scripts/gpu/setup_scene_runtime.sh")"
    [ -n "$expected" ] && [ -f "$SCENE/$name" ] && [ "$(sha_of "$SCENE/$name")" = "$expected" ] || return 1
  done
  local torch_home="${TORCH_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/torch}"
  [ -s "$torch_home/hub/checkpoints/vgg16-397923af.pth" ] || return 1
  "$SCENE/bin/python" -c 'import torch, torchvision, coacd, cv2, skimage, trimesh, lpips; from moge.model.v2 import MoGeModel; from sam2.build_sam import build_sam2; from gen2.script.predictor import EgoblurDetector; from pxr import UsdVol; assert hasattr(UsdVol, "ParticleField3DGaussianSplat")'
}

install_scene() {
  [ "$SKIP_GPU_CHECK" = 1 ] && export R2S_SKIP_GPU_CHECK=1
  bash "$REPO/scripts/gpu/setup_scene_runtime.sh" "$SCENE"
}
