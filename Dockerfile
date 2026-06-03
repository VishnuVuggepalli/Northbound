# Northbound — single-image build: Vite SPA + FastAPI API in one container.
# The backend serves the built frontend (mount_spa) so there is one process,
# one port. Two stages keep the runtime image lean (no compilers).
#
# PREREQUISITE: build the SPA on the host first (the in-container npm install is
# OOM-prone on constrained hosts, and the host toolchain is already set up):
#     npm --prefix frontend ci   # first time only
#     npm --prefix frontend run build
# That produces frontend/dist, which this image copies in. `make docker` or the
# compose `build` wraps both steps.

# ---------------------------------------------------------------------------
# Stage 1 — build a venv with all Python deps (+ the northbound package)
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
# No apt build deps: every dependency (lxml, cryptography, bcrypt, ncclient,
# napalm, …) ships a self-contained cp311 manylinux wheel, so pip never compiles.
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# pyproject + sources are needed to build/install the package (ships the TextFSM
# templates as package-data, so the venv contains everything at runtime).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# ---------------------------------------------------------------------------
# Stage 2 — slim runtime: venv + migrations + prebuilt SPA, no build tooling
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime
# No apt: the wheels bundle their native libs (libxml2/libxslt/openssl), and the
# drivers use pure-python transports (asyncssh/ncclient) — no system binaries.

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    NB_ENVIRONMENT=production \
    NB_FRONTEND_DIST=/app/frontend/dist \
    NB_DB_URL=sqlite+aiosqlite:////data/northbound.db

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Migrations + seed are run at start; alembic.ini resolves script_location to
# ./alembic. The northbound package itself lives in the venv.
COPY alembic.ini seed.py ./
COPY alembic ./alembic
# Prebuilt SPA (built on the host — see header). Served by mount_spa via
# NB_FRONTEND_DIST below.
COPY frontend/dist ./frontend/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /data \
    && useradd --create-home --uid 10001 app \
    && chown -R app:app /app /data
USER app

EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8090/health').status==200 else 1)" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "northbound.main:app", "--host", "0.0.0.0", "--port", "8090"]
