#!/usr/bin/env bash
# Runtime ObjectGS: việc cài thuộc scripts/gpu/setup_objectgs_runtime.sh (commit ghim đọc từ objectgs.py).
objectgs_pin() {
  sed -n "s/^$1 = \"\([0-9a-f]\{40\}\)\"\$/\1/p" "$REPO/src/services/scene/objectgs.py" | head -n1
}

recipe_objectgs() { echo "objectgs $(objectgs_pin OBJECTGS_COMMIT) $(objectgs_pin GSPLAT_COMMIT) $(objectgs_pin GLM_COMMIT)"; }

verify_objectgs() {
  [ -x "$OBJGS/python/bin/python" ] || return 1
  [ "$(git -C "$OBJGS/ObjectGS" rev-parse HEAD 2>/dev/null)" = "$(objectgs_pin OBJECTGS_COMMIT)" ] || return 1
  [ "$(git -C "$OBJGS/gsplat-object" rev-parse HEAD 2>/dev/null)" = "$(objectgs_pin GSPLAT_COMMIT)" ] || return 1
  [ "$(git -C "$OBJGS/glm" rev-parse HEAD 2>/dev/null)" = "$(objectgs_pin GLM_COMMIT)" ]
}

install_objectgs() {
  local args=("$OBJGS")
  [ -n "${OBJECTGS_WHEELS:-}" ] && args+=(--wheels "$OBJECTGS_WHEELS")
  [ "$SKIP_GPU_CHECK" = 1 ] && args+=(--skip-gpu-check)
  bash "$REPO/scripts/gpu/setup_objectgs_runtime.sh" "${args[@]}"
}
