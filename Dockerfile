# syntax=docker/dockerfile:1
#
# API image for the portable Studio stack.
#
# The regular Dockerfile is the control-plane image.  It includes the pinned
# Node/splat-transform runtime needed when an imported Gaussian asset must be
# converted to SOG or when geometry commands are requested.  Heavy CUDA/SAM2/
# Brush dependencies remain in Dockerfile.gpu and are enabled only by the
# explicit GPU Compose override.

FROM node:24.15.0-bookworm-slim AS node-runtime

WORKDIR /opt/real2sim/runtime
RUN npm init -y >/dev/null 2>&1 \
    && npm install --no-audit --no-fund --omit=dev \
       @playcanvas/splat-transform@3.6.6

FROM python:3.12.14-slim-bookworm AS dependencies

WORKDIR /app

RUN pip install --no-cache-dir uv==0.9.4
COPY requirements.in requirements.lock.txt ./
RUN uv pip sync --system requirements.lock.txt \
    && uv pip check

# API-side USD export is intentionally kept separate from the core lockfile.
COPY requirements-usd.lock.txt ./
RUN uv venv /opt/usd_runtime --python /usr/local/bin/python \
    && uv pip sync --python /opt/usd_runtime/bin/python requirements-usd.lock.txt \
    && uv pip check --python /opt/usd_runtime/bin/python

FROM python:3.12.14-slim-bookworm

WORKDIR /app

# ffmpeg is used by the API thumbnail path.  libstdc++ is required by the
# PlayCanvas native pieces when they are invoked.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg libgcc-s1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/bin/npm /usr/local/bin/npm
COPY --from=node-runtime /usr/local/bin/npx /usr/local/bin/npx
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node-runtime /opt/real2sim/runtime /opt/real2sim/runtime

# `uv pip sync --system` installs core Python packages into /usr/local.
COPY --from=dependencies /usr/local /usr/local
COPY --from=dependencies /opt/usd_runtime /opt/usd_runtime

ENV PATH=/opt/real2sim/runtime/node_modules/.bin:/usr/local/bin:$PATH \
    PRODUCT_SCENE_RUNTIME_PYTHON=/opt/usd_runtime/bin/python \
    NODE_PATH=/opt/real2sim/runtime/node_modules

# Keep the bind-mount ownership contract deterministic: data-init grants this
# UID write access before the unprivileged API/restore services start.
RUN useradd --uid 1000 --user-group --create-home --shell /usr/sbin/nologin appuser

# The root .dockerignore excludes data, frontend and local credentials.  The
# archive is restored into the bind-mounted /app/data volume by the operator;
# it is never copied into the image.
COPY . .
RUN mkdir -p /app/data /package \
    && chown -R appuser:appuser /app /opt/real2sim/runtime

USER appuser

ENV REC04_SPLAT_MODULE_PATH=/opt/real2sim/runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs \
    REC05_VOXEL_CLI=/opt/real2sim/runtime/node_modules/@playcanvas/splat-transform/bin/cli.mjs \
    REC05_VOXEL_MODULE_PATH=/opt/real2sim/runtime/node_modules/@playcanvas/splat-transform/dist/index.mjs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:' + __import__('os').environ.get('PORT', '8000') + '/health')" || exit 1

ENTRYPOINT ["python", "-m", "scripts.studio.container_entrypoint"]
CMD ["serve"]
