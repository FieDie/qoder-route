# ─────────────────────────────────────────────────────────────────────────────
# QoderRoute — single-container image
#
# Stage 1 builds the React/Vite frontend and also donates its glibc-linked
# `node` binary to the runtime stage for the WASM signer sidecar.
# Stage 2 is the FastAPI app + signer assets + built SPA.
#
# The signer sidecar is spawned by the backend itself at startup
# (app/services/signer_service.py, listening on 127.0.0.1:8123 inside the
# container), so no extra process manager is required.
# ─────────────────────────────────────────────────────────────────────────────

# Base images are parameterised so that builds behind unreachable-to-Docker-Hub
# networks can swap in a registry-prefixed mirror (e.g.
# docker.m.daocloud.io/library/python:3.11-slim-bookworm) via
# --build-arg or the compose args below — defaults stay the official names.
ARG NODE_IMAGE=node:22-bookworm-slim
ARG PYTHON_IMAGE=python:3.11-slim-bookworm

FROM ${NODE_IMAGE} AS frontend-build
WORKDIR /build/frontend
# Dependency layer first for better cache reuse.
# (The repo intentionally carries no package-lock.json → npm install.)
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

# Dependencies layer first for better cache reuse.
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

# `node` binary for the signer sidecar (spawned via PATH lookup by
# signer_service). Both stages are Debian bookworm/glibc, so the official
# binary runs as-is; libstdc++6 stays explicit in case the base trims it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libstdc++6 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node

# Backend code + signer assets (wasm/mjs). signer_service writes its lock,
# log and pid here at runtime → this directory must stay writable.
COPY backend/app ./app
COPY backend/run.py ./
COPY backend/signer ./signer

# Built SPA — FRONTEND_DIST in app/main.py resolves to <repo>/frontend/dist.
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

# Non-root runtime user; pre-create the state dir so an arriving named
# volume or bind mount can also start out empty.
RUN useradd --create-home --uid 1000 qrr \
 && mkdir -p /app/backend/data \
 && chown -R qrr:qrr /app/backend/signer /app/backend/data
USER qrr

EXPOSE 8010

# /api/health returns 200 only when both the app and the signer answer.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request,sys; port=int(os.environ.get('PORT','8010')); r=urllib.request.urlopen('http://127.0.0.1:%d/api/health' % port, timeout=4); sys.exit(0 if r.status == 200 else 1)"

CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8010}"]
