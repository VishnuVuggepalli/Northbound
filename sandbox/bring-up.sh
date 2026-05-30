#!/usr/bin/env bash
# Northbound sandbox bring-up.
#
# Deploys the containerlab topology (falls back to raw `docker run` if
# containerlab is absent), enables eAPI on cEOS if present, and prints the
# mgmt IPs + ready-to-run validation commands.
#
# Usage:
#   sandbox/bring-up.sh            # full topology
#   FRR_ONLY=1 sandbox/bring-up.sh # only the freely-pullable FRR/host path
set -euo pipefail

SANDBOX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOPO="${SANDBOX_DIR}/topology.clab.yml"

CEOS_IMAGE="${CEOS_IMAGE:-ceos:4.32.0F}"
FRR_IMAGE="${FRR_IMAGE:-quay.io/frrouting/frr:9.1.0}"
HOST_IMAGE="${HOST_IMAGE:-alpine:latest}"
export CEOS_IMAGE FRR_IMAGE HOST_IMAGE

echo "== Northbound sandbox bring-up =="
echo "  cEOS image: ${CEOS_IMAGE}"
echo "  FRR image:  ${FRR_IMAGE}"
echo "  host image: ${HOST_IMAGE}"
echo

# --- preflight: which images do we actually have? ---
have_ceos=0
if docker image inspect "${CEOS_IMAGE}" >/dev/null 2>&1; then
    have_ceos=1
else
    echo "WARN: cEOS image '${CEOS_IMAGE}' not found locally."
    echo "      Arista live-validation will be SKIPPED. See sandbox/README.md to import it."
fi

docker image inspect "${FRR_IMAGE}" >/dev/null 2>&1 || docker pull "${FRR_IMAGE}"
docker image inspect "${HOST_IMAGE}" >/dev/null 2>&1 || docker pull "${HOST_IMAGE}"

# --- deploy ---
if command -v containerlab >/dev/null 2>&1; then
    echo "== Deploying via containerlab =="
    if [[ "${have_ceos}" -eq 0 ]]; then
        # Deploy only the nodes whose images exist. containerlab has no
        # per-node skip flag, so when cEOS is missing we deploy the FRR-only
        # fallback topology generated on the fly.
        gen="${SANDBOX_DIR}/.topology.frr-only.clab.yml"
        cat > "${gen}" <<EOF
name: nb-sandbox
topology:
  nodes:
    frr1:
      kind: linux
      image: ${FRR_IMAGE}
      binds:
        - files/frr/daemons:/etc/frr/daemons:ro
        - files/frr/frr.conf:/etc/frr/frr.conf:ro
        - files/frr/entrypoint.sh:/nb-entrypoint.sh:ro
      cmd: /bin/sh /nb-entrypoint.sh
    host1:
      kind: linux
      image: ${HOST_IMAGE}
      cmd: sleep infinity
EOF
        ( cd "${SANDBOX_DIR}" && containerlab deploy -t "${gen}" --reconfigure )
    else
        ( cd "${SANDBOX_DIR}" && containerlab deploy -t "${TOPO}" --reconfigure )
    fi
else
    echo "containerlab not found — using raw docker run fallback (FRR + host only)."
    docker network inspect nb-sandbox >/dev/null 2>&1 || docker network create nb-sandbox >/dev/null
    docker rm -f nb-frr1 nb-host1 >/dev/null 2>&1 || true
    docker run -d --name nb-frr1 --network nb-sandbox \
        -v "${SANDBOX_DIR}/files/frr/daemons:/etc/frr/daemons:ro" \
        -v "${SANDBOX_DIR}/files/frr/frr.conf:/etc/frr/frr.conf:ro" \
        -v "${SANDBOX_DIR}/files/frr/entrypoint.sh:/nb-entrypoint.sh:ro" \
        --entrypoint /bin/sh "${FRR_IMAGE}" /nb-entrypoint.sh >/dev/null
    docker run -d --name nb-host1 --network nb-sandbox "${HOST_IMAGE}" sleep infinity >/dev/null
fi

echo
echo "== Node mgmt IPs =="
print_ip() {
    local cname="$1" label="$2"
    local ip
    ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "${cname}" 2>/dev/null | awk '{print $1}')"
    [[ -n "${ip}" ]] && printf "  %-22s %s\n" "${label} (${cname}):" "${ip}"
}
# containerlab prefixes containers with clab-<labname>-
for n in clab-nb-sandbox-ceos1 clab-nb-sandbox-frr1 clab-nb-sandbox-host1 clab-nb-sandbox-host2 nb-frr1 nb-host1; do
    print_ip "${n}" "${n##*-}"
done

# --- enable eAPI on cEOS (idempotent; startup-config already does it) ---
if [[ "${have_ceos}" -eq 1 ]]; then
    echo
    echo "== Ensuring eAPI enabled on cEOS =="
    docker exec clab-nb-sandbox-ceos1 Cli -p 15 -c $'configure\nmanagement api http-commands\nprotocol http\nno shutdown\nend' 2>/dev/null \
        && echo "  eAPI http server enabled (user admin / pass nbsandbox)" \
        || echo "  WARN: could not auto-enable eAPI; do it manually via 'docker exec -it clab-nb-sandbox-ceos1 Cli'"
fi

echo
echo "== Validate =="
echo "  # Arista (only if cEOS came up) — point the driver at ceos1 mgmt IP:"
echo "  python sandbox/record_fixtures.py --platform arista --host <ceos1-ip> \\"
echo "         --username admin --password nbsandbox --scheme http"
echo
echo "  # FRR/FreeBSD SSH read path — transport-layer live check:"
echo "  python sandbox/validate_ssh.py --host <frr1-ip> --username nbadmin --password nbsandbox"
echo
echo "Tear down with: sandbox/tear-down.sh"
