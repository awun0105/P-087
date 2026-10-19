#!/usr/bin/env bash
set -euo pipefail
[ "${OMNI_KIT_ACCEPT_EULA:-NO}" = YES ] || {
  echo 'Isaac execution requires OMNI_KIT_ACCEPT_EULA=YES in worker configuration' >&2
  exit 1
}
PY="${R2S_ROOT:-/opt/real2sim}/isaac_runtime/bin/python"
[ -x "$PY" ] || { echo 'Isaac runtime is missing; build Dockerfile.gpu --target isaac' >&2; exit 1; }
# Avoid leaking CUDA 11.8/ObjectGS and application Python paths into Kit.
unset PYTHONPATH PYTHONHOME CUDA_HOME CPLUS_INCLUDE_PATH
if [ "$(id -u)" = 0 ]; then export OMNI_KIT_ALLOW_ROOT=1; fi
exec "$PY" "$@"
