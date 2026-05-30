#!/usr/bin/env bash
# Northbound sandbox tear-down. Destroys the containerlab lab and any raw
# docker-run fallback containers/networks. Safe to run repeatedly.
set -uo pipefail

SANDBOX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== Northbound sandbox tear-down =="

if command -v containerlab >/dev/null 2>&1; then
    for topo in "${SANDBOX_DIR}/topology.clab.yml" "${SANDBOX_DIR}/.topology.frr-only.clab.yml"; do
        if [[ -f "${topo}" ]]; then
            ( cd "${SANDBOX_DIR}" && containerlab destroy -t "${topo}" --cleanup ) 2>/dev/null || true
        fi
    done
    rm -f "${SANDBOX_DIR}/.topology.frr-only.clab.yml"
fi

# Raw docker-run fallback cleanup.
docker rm -f nb-frr1 nb-host1 >/dev/null 2>&1 || true
docker network rm nb-sandbox >/dev/null 2>&1 || true

echo "== done =="
