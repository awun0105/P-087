#!/bin/bash
# Setup script cho AI20K project

set -e

echo "=== AI20K Project Setup ==="

# Check Python version
python3.12 -c "import sys; assert (3, 12) <= sys.version_info < (3, 13), 'Python >=3.12 and <3.13 is required'"
echo "Python version OK"

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.lock.txt -r requirements-dev.lock.txt

# Create .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env — please edit with your API keys"
fi

# Create data directories
mkdir -p data/chroma

echo "Setup complete! Run: uvicorn src.main:app --reload"
