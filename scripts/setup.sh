#!/bin/bash
# Setup script cho AI20K project

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
MODE="${1:---development}"
[[ "$MODE" = --development || "$MODE" = --production ]] && [ "$#" -le 1 ] || {
    echo 'Usage: scripts/setup.sh [--development|--production]' >&2
    exit 2
}

echo "=== AI20K Project Setup ==="

# Check Python version
python3.12 -c "import sys; assert (3, 12) <= sys.version_info < (3, 13), 'Python >=3.12 and <3.13 is required'"
echo "Python version OK"

# Create virtual environment
[ -x .venv/bin/python ] || python3.12 -m venv .venv

# Install build/environment tools (not added to core requirements)
# Keep the installer outside .venv: uv sync removes packages absent from the lock,
# including uv itself. Do not modify a global Python installation.
TOOLING="$(mktemp -d)"
trap 'rm -rf "$TOOLING"' EXIT
python3.12 -m venv "$TOOLING"
"$TOOLING/bin/python" -m pip install uv==0.9.4
UV="$TOOLING/bin/uv"

# Sync dependencies using uv
LOCKS=(requirements.lock.txt)
if [ "$MODE" = --development ]; then LOCKS+=(requirements-dev.lock.txt); fi
"$UV" pip sync --python .venv/bin/python --require-hashes "${LOCKS[@]}"

# Run integrity check
"$UV" pip check --python .venv/bin/python

# Create .env if not exists
if [ "$MODE" = --development ] && [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env — please edit with your API keys"
fi

# Create data directories
mkdir -p data/chroma

if [ "$MODE" = --development ]; then
    echo "Setup complete! Run: .venv/bin/uvicorn src.main:app --reload"
else
    echo "Core runtime installed. Configure server environment before starting the API; GPU tools use scripts/gpu/install.sh."
fi
