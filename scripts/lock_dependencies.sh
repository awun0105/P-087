#!/bin/bash
set -e

echo "Generating requirements.lock.txt (Core)..."
uv pip compile --generate-hashes --python-version 3.12.14 requirements.in -o requirements.lock.txt

echo "Generating requirements-dev.lock.txt (Dev)..."
uv pip compile --generate-hashes --python-version 3.12.14 requirements-dev.in -o requirements-dev.lock.txt

echo "Generating requirements-offline.lock.txt (Offline dataset tooling)..."
uv pip compile --generate-hashes --python-version 3.12.14 requirements-offline.in -o requirements-offline.lock.txt

echo "Lock files generated successfully."
