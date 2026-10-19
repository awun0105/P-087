#!/usr/bin/env bash
# Kiểm runtime GPU đã cài ở <gốc>: nạp <gốc>/runtime.env (chỉ biến chưa có trong môi trường), rồi chạy preflight.
#   scripts/gpu/doctor.sh <gốc>
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO
[ -n "${1:-}" ] || { echo "dùng: doctor.sh <gốc>" >&2; exit 2; }
GOC="$(cd "$1" && pwd)"
source "$REPO/scripts/gpu/install.d/_lib.sh"
load_runtime_env "$GOC/runtime.env"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
cd "$REPO"
exec "$PY" -m scripts.kaggle.preflight
