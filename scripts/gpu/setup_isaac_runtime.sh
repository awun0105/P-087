#!/usr/bin/env bash
# Optional Isaac Sim 5.1 runtime, isolated from app Python 3.12 and ObjectGS Python 3.8.
set -euo pipefail
[ "${ISAAC_ACCEPT_EULA:-NO}" = YES ] || {
  echo 'Isaac installation requires operator license acceptance: ISAAC_ACCEPT_EULA=YES' >&2
  exit 1
}
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO="$ROOT"
source "$ROOT/scripts/gpu/install.d/_lib.sh"
DEST="${1:?Isaac runtime destination required}"
command -v uv >/dev/null || die 'uv is required'
[ -x "$DEST/bin/python" ] || uv venv --python 3.11 "$DEST"
uv pip install --python "$DEST/bin/python" --index-strategy unsafe-best-match \
  --extra-index-url https://pypi.nvidia.com "isaacsim[all,extscache]==$(pin ISAAC_VERSION)"
uv pip check --python "$DEST/bin/python"
# Query installed metadata without starting Kit or requiring GPU access during build.
"$DEST/bin/python" -c 'import importlib.metadata as m; print("Isaac Sim", m.version("isaacsim"))'
uv pip freeze --python "$DEST/bin/python" > "$DEST/installed.txt"
