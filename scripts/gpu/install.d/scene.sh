#!/usr/bin/env bash
# Runtime tách theo vật (SAM2, gsplat, CoACD, LaMa, MoGe): việc cài thuộc scripts/gpu/setup_scene_runtime.sh.
recipe_scene() { echo "scene $(sha_of "$REPO/scripts/gpu/setup_scene_runtime.sh")"; }

verify_scene() {
  [ -x "$SCENE/bin/python" ] && [ -f "$SCENE/checkpoints/sam2.1_hiera_tiny.pt" ] && [ -f "$SCENE/weights/big-lama.pt" ]
}

install_scene() {
  [ "$SKIP_GPU_CHECK" = 1 ] && export R2S_SKIP_GPU_CHECK=1
  bash "$REPO/scripts/gpu/setup_scene_runtime.sh" "$SCENE"
}
