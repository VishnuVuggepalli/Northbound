#!/bin/sh
# Container entrypoint: validate required secrets, apply DB migrations, optional
# first-run seed, then exec the server (CMD).
set -e

: "${NB_MASTER_KEY:?NB_MASTER_KEY is required (Fernet key — encrypts device creds at rest)}"
: "${NB_SECRET_KEY:?NB_SECRET_KEY is required (JWT signing secret)}"

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

echo "[entrypoint] starting: $*"
exec "$@"
