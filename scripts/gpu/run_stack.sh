#!/usr/bin/env bash
# Chạy đủ Studio MVP trên một máy: FastAPI + queue worker + Next.js.
#
#   scripts/gpu/run_stack.sh scripts/gpu/studio.env            # production build
#   STUDIO_FRONTEND=dev scripts/gpu/run_stack.sh studio.env    # next dev
#
# Dừng bằng Ctrl+C: script gửi SIGTERM cho cả ba process (worker dọn COLMAP/Brush).
set -euo pipefail

env_file="${1:?Cần đường dẫn file env (xem scripts/gpu/studio.env.example)}"
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

python_bin="${STUDIO_PYTHON:-$root/.venv/bin/python}"
mkdir -p "$(dirname "${ARTIFACT_ROOT:?}")" "${PRODUCT_WORKER_ROOT:?}"

if [ ! -f "${PRODUCT_RUNTIME_MANIFEST:?}" ]; then
  echo "Chưa có runtime manifest, sinh mới: $PRODUCT_RUNTIME_MANIFEST"
  "$python_bin" -m scripts.gpu.make_runtime_manifest --out "$PRODUCT_RUNTIME_MANIFEST"
fi

if [ ! -f frontend/public/editor/index.html ]; then
  echo "Build SuperSplat editor (lần đầu)…"
  (cd frontend && npm run build:editor)
fi

pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  wait || true
}
trap cleanup EXIT INT TERM

"$python_bin" -m uvicorn src.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}" &
pids+=($!)
"$python_bin" -m src.services.orchestration.jobs.worker_cli &
pids+=($!)
if [ "${STUDIO_FRONTEND:-prod}" = "dev" ]; then
  (cd frontend && npm run dev -- --port "${STUDIO_WEB_PORT:-3000}") &
else
  (cd frontend && npm run build && npm run start -- --port "${STUDIO_WEB_PORT:-3000}") &
fi
pids+=($!)

echo "Studio: http://localhost:${STUDIO_WEB_PORT:-3000}  ·  API: http://localhost:${APP_PORT:-8000}/docs"
wait -n
