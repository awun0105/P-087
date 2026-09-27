# ---- Stage 1: Dependencies ----
# Dùng đúng lock mà CI và scripts/setup.sh dùng, nên image không thể lệch với test.
FROM python:3.12.14-slim-bookworm AS deps

WORKDIR /app

RUN pip install --no-cache-dir uv==0.9.4
COPY requirements.in requirements.lock.txt ./
RUN uv pip sync --system requirements.lock.txt \
    && uv pip check

# ---- Stage 2: Production ----
FROM python:3.12.14-slim-bookworm

WORKDIR /app

# `uv pip sync --system` cài vào /usr/local của base image nên không cần copy site-packages.
COPY --from=deps /usr/local /usr/local

ENV PATH=/usr/local/bin:$PATH

# Security: run as non-root user
RUN useradd -m appuser

# Copy application code
COPY . .

# Create data directory with correct ownership
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
