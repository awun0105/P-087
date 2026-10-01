# ---- Stage 1: Dependencies ----
# Dùng đúng lock mà CI và scripts/setup.sh dùng, nên image không thể lệch với test.
FROM python:3.12.14-slim-bookworm AS deps

WORKDIR /app

RUN pip install --no-cache-dir uv==0.9.4
COPY requirements.in requirements.lock.txt ./
RUN uv pip sync --system requirements.lock.txt \
    && uv pip check

# Runtime xuất USD lai (ADR 0007): `usd-core` tách khỏi dependency của app (RUNTIME_POLICY §2), không cần GPU.
# Có nó thì API tự dựng được gói USD lai khi worker GPU ở máy khác; phiên bản ghim như scripts/gpu/setup_scene_runtime.sh.
RUN uv venv /opt/usd_runtime --python /usr/local/bin/python \
    && uv pip install --python /opt/usd_runtime/bin/python usd-core==26.8 numpy trimesh==5.1.0

# ---- Stage 2: Production ----
FROM python:3.12.14-slim-bookworm

WORKDIR /app

# `uv pip sync --system` cài vào /usr/local của base image nên không cần copy site-packages.
COPY --from=deps /usr/local /usr/local
COPY --from=deps /opt/usd_runtime /opt/usd_runtime

ENV PATH=/usr/local/bin:$PATH \
    PRODUCT_SCENE_RUNTIME_PYTHON=/opt/usd_runtime/bin/python

# Security: run as non-root user
RUN useradd -m appuser

# Copy application code
COPY . .

# Create data directory with correct ownership
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:' + __import__('os').environ.get('PORT', '8000') + '/health')" || exit 1

# Railway/Render cấp cổng qua $PORT; chạy local vẫn mặc định 8000.
CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
