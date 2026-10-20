#!/usr/bin/env bash
# Runtime ObjectGS: việc cài thuộc scripts/gpu/setup_objectgs_runtime.sh (commit ghim đọc từ objectgs.py).
# Nếu python và ba repo đã đúng nhưng extension gsplat chưa được biên dịch sẵn (cache trống), chỉ biên dịch sẵn.
objectgs_pin() {
  sed -n "s/^$1 = \"\([0-9a-f]\{40\}\)\"\$/\1/p" "$REPO/src/services/scene/objectgs.py" | head -n1
}

recipe_objectgs() {
  echo "objectgs $(objectgs_pin OBJECTGS_COMMIT) $(objectgs_pin GSPLAT_COMMIT) $(objectgs_pin GLM_COMMIT) $(sha_of "$REPO/scripts/gpu/setup_objectgs_runtime.sh") $(sha_of "$REPO/configs/runtime/pins.env")"
  sha256sum "$REPO"/configs/runtime/objectgs/*.txt
}

objectgs_repos_ok() {
  [ -x "$OBJGS/python/bin/python" ] || return 1
  [ "$(git -C "$OBJGS/ObjectGS" rev-parse HEAD 2>/dev/null)" = "$(objectgs_pin OBJECTGS_COMMIT)" ] || return 1
  [ "$(git -C "$OBJGS/gsplat-object" rev-parse HEAD 2>/dev/null)" = "$(objectgs_pin GSPLAT_COMMIT)" ] || return 1
  [ "$(git -C "$OBJGS/glm" rev-parse HEAD 2>/dev/null)" = "$(objectgs_pin GLM_COMMIT)" ]
}

# Nạp kernel gsplat đúng môi trường lúc chạy ObjectGS (cùng hàm với doctor: preflight.objectgs_runtime). Cache khớp thì
# chỉ mất vài giây; cache trống hoặc biên dịch cho cấu hình khác thì đây là lúc biên dịch (vài phút).
# Môi trường lấy từ chính write_runtime_env nên không có bảng biến thứ hai để lệch. Lệnh chạy bằng Python của repo
# (có pydantic); Python của ObjectGS chỉ là đích được probe, qua PRODUCT_OBJECTGS_RUNTIME_PYTHON.
objectgs_probe() {
  local tmp status=0
  tmp="$(mktemp -d)"
  write_runtime_env "$tmp/runtime.env" objectgs
  (
    load_runtime_env "$tmp/runtime.env"
    unset CPATH C_INCLUDE_PATH  # header của Python khác sẽ làm kernel gsplat 3.8 biên dịch sai
    cd "$REPO" && "$(py_bin)" -c 'import sys; from scripts.kaggle.preflight import objectgs_extension_loads; ok, detail = objectgs_extension_loads(); print(detail); sys.exit(0 if ok else 1)'
  ) || status=$?
  rm -f "$tmp/runtime.env" "$tmp/runtime.env.tmp"
  rmdir "$tmp"
  return "$status"
}

verify_objectgs() {
  objectgs_repos_ok && objectgs_probe
}

install_objectgs() {
  local args=("$OBJGS")
  [ -n "${OBJECTGS_WHEELS:-}" ] && args+=(--wheels "$OBJECTGS_WHEELS")
  [ "$SKIP_GPU_CHECK" = 1 ] && args+=(--skip-gpu-check)
  bash "$REPO/scripts/gpu/setup_objectgs_runtime.sh" "${args[@]}"
}
