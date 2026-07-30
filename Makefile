.PHONY: install dev test testv lint format typecheck check fix clean \
        frontend-install frontend-build frontend-test build seed migrate \
        serve run-prod ship verify docker-build docker-build-selfcontained \
        docker-up docker-down

# ───────────────────────── Backend (existing) ─────────────────────────

install:
	pip install -e ".[dev]"

dev:
	uvicorn northbound.main:app --reload --host 0.0.0.0 --port 1211

test:
	pytest

testv:
	pytest -v

lint:
	ruff check src tests

format:
	ruff format src tests

typecheck:
	pyright

check: lint typecheck format

fix:
	ruff check --fix src tests
	make check

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .ruff_cache .pytest_cache

# ───────────────────────── Frontend ─────────────────────────

frontend-install:
	cd frontend && (npm ci || npm install)

# Build the Vite SPA into frontend/dist. main.py serves it in place via the
# NB_FRONTEND_DIST default ("frontend/dist", resolved against the repo root) —
# no copy step needed.
frontend-build: frontend-install
	cd frontend && npm run build

frontend-test:
	cd frontend && npm test

# ───────────────────────── Build / data / run ─────────────────────────

# Full product build: just the frontend bundle. The backend is served from
# source (single-VM deploy, no packaging step). dist is served in place.
build: frontend-build

# Apply DB migrations to the configured NB_DB_URL.
migrate:
	alembic upgrade head

# Create baseline users (admin + alice). Idempotent. Reads NB_SEED_*_PASSWORD;
# generates+prints a random one if unset (dev). Pass ARGS=--with-sample-devices.
seed:
	python seed.py $(ARGS)

# Run the app (single worker per principal-engineering D9). Serves API + SPA.
serve:
	uvicorn northbound.main:app --host 0.0.0.0 --port 8080

run-prod: serve

# Full local verification: backend gate.
verify: check test

# Deploy. On a real host this is build + migrate + restart the systemd unit.
# Here it documents the steps; wire SSH_HOST / DEPLOY_DIR for an actual push.
ship: build migrate
	@echo "── ship ─────────────────────────────────────────────────────────"
	@echo "Local build + migrate complete."
	@echo "To deploy to a host (see deploy/northbound.service + README):"
	@echo "  rsync -a --delete --exclude .git --exclude .venv \\"
	@echo "    ./  \$$SSH_HOST:\$$DEPLOY_DIR/"
	@echo "  ssh \$$SSH_HOST 'cd \$$DEPLOY_DIR && .venv/bin/alembic upgrade head \\"
	@echo "    && sudo systemctl restart northbound'"
	@echo "─────────────────────────────────────────────────────────────────"

# ───────────────────────── Docker ─────────────────────────

# Build the single SPA+API image. The SPA is built on the host first (the
# in-container npm install is OOM-prone) and copied into the image.
# --network=host lets pip reach PyPI on hosts where the build network has no DNS.
docker-build: frontend-build
	docker build --network=host -t northbound:latest .

# Self-contained build: builds the SPA INSIDE the image (Node stage) — no host
# prebuild, no host toolchain. Heavier (needs ~1-2 GB RAM in the build) and can
# OOM on constrained hosts; that's why it's not the default. See Dockerfile.selfcontained.
docker-build-selfcontained:
	DOCKER_BUILDKIT=1 docker build -f Dockerfile.selfcontained --network=host -t northbound:latest .

# Compose v2 plugin (`docker compose`) when present, else the legacy v1 binary
# (`docker-compose`). The lab node ships only v1.29.2, so hardcoding either one
# breaks on some host.
COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")

# Run via compose (reads .env — see .env.example). Builds first.
docker-up: frontend-build
	$(COMPOSE) up --build -d

docker-down:
	$(COMPOSE) down

# Production deploy: host networking + in-app TLS, the shape running on the lab
# node. One command instead of a hand-typed `docker run` with a dozen flags.
# Host prerequisites (certs, healthcheck, 443 redirect) — see deploy/README-prod.md.
deploy-prod: frontend-build
	$(COMPOSE) -f docker-compose.prod.yml up --build -d
	@echo "waiting for health…"
	@for i in $$(seq 1 30); do \
	  s=$$(docker inspect -f '{{.State.Health.Status}}' northbound 2>/dev/null || echo starting); \
	  [ "$$s" = healthy ] && echo "healthy" && exit 0; \
	  [ "$$s" = unhealthy ] && echo "UNHEALTHY — docker logs northbound" && exit 1; \
	  sleep 3; \
	done; echo "timed out waiting for health" && exit 1

deploy-prod-down:
	$(COMPOSE) -f docker-compose.prod.yml down
