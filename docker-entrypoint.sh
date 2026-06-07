#!/bin/sh
# Container entrypoint: validate required secrets, apply DB migrations, optional
# first-run seed, then exec the server (CMD).
set -e

# Each secret may come from an inline env var OR a *_FILE path (Docker/K8s/systemd
# secrets convention — see config._read_secret_file). Require exactly one source.
if [ -z "${NB_MASTER_KEY:-}" ] && [ -z "${NB_MASTER_KEY_FILE:-}" ]; then
    echo "NB_MASTER_KEY or NB_MASTER_KEY_FILE is required (Fernet key — encrypts device creds at rest)" >&2
    exit 1
fi
if [ -z "${NB_SECRET_KEY:-}" ] && [ -z "${NB_SECRET_KEY_FILE:-}" ]; then
    echo "NB_SECRET_KEY or NB_SECRET_KEY_FILE is required (JWT signing secret)" >&2
    exit 1
fi

echo "[entrypoint] applying database migrations (alembic upgrade head)…"
alembic upgrade head

# Seed baseline users on first run when NB_SEED=1. Idempotent: re-running only
# inserts what's missing. Set NB_SEED_SAMPLE=1 to also add demo devices.
if [ "${NB_SEED:-0}" = "1" ]; then
    echo "[entrypoint] seeding users${NB_SEED_SAMPLE:+ + sample devices}…"
    if [ "${NB_SEED_SAMPLE:-0}" = "1" ]; then
        python seed.py --with-sample-devices
    else
        python seed.py
    fi
fi

# Multi-worker: scale uvicorn workers via NB_WEB_CONCURRENCY (default 1). Only
# appended when the command is uvicorn so an overridden command is left intact.
# Migrations above run ONCE here (before workers fork), so N workers never race
# `alembic upgrade`. The scheduler self-elects a single leader across workers
# (Postgres advisory lock — see services.scheduler_lease), so background jobs
# never run N times.
workers="${NB_WEB_CONCURRENCY:-1}"
if [ "$workers" -gt 1 ] 2>/dev/null && [ "$1" = "uvicorn" ]; then
    if [ -z "${NB_RATELIMIT_STORAGE_URI:-}" ]; then
        echo "[entrypoint] WARNING: NB_WEB_CONCURRENCY=$workers without NB_RATELIMIT_STORAGE_URI" \
             "— rate limits are per-worker (about N times the configured limit). Set a shared" \
             "Redis store for correct global limits."
    fi
    echo "[entrypoint] multi-worker: $workers uvicorn workers"
    set -- "$@" --workers "$workers"
fi

echo "[entrypoint] starting: $*"
exec "$@"
