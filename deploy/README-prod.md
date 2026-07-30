# Production deploy (host-network + in-app TLS)

One command once the host prerequisites exist:

```bash
make deploy-prod        # build SPA + image, compose up, wait for healthy
make deploy-prod-down
```

That runs `docker-compose.prod.yml`, which captures the full runtime shape —
host networking, TLS flags, cert mount, healthcheck override, restart policy.

## Why not Terraform

Terraform provisions *infrastructure* and reconciles it against a state file.
This deployment is one container on one already-existing box. Using Terraform
here would add a state file, a provider dependency
(`kreuzwerker/docker`), and a drift-reconciliation model, in exchange for
nothing Compose does not already do — while handling `docker build` and
`network_mode: host` less well. Terraform earns its keep when *the box itself*
is provisioned (cloud VM, disks, DNS, firewall). If Northbound ever moves to
cloud instances, Terraform belongs at that layer, with Compose still owning the
container.

Layering, for reference:

| Layer | Tool |
|---|---|
| the machine (VM, disk, DNS, firewall) | Terraform — only if cloud-provisioned |
| OS-level state (packages, certs, systemd units, sysctl) | Ansible, or `provision-host.sh` |
| the container | **Compose — `docker-compose.prod.yml`** |

## Host prerequisites

These are OS-level and outside Compose's remit. Today they are configured by
hand on the node; an Ansible playbook is the natural next step if this ever
needs to stand up on a second host.

1. **Secrets** — `.env` with `NB_MASTER_KEY` and `NB_SECRET_KEY` (see
   `.env.example`). `NB_MASTER_KEY` **must not change** across rebuilds or the
   device credentials encrypted in the DB will not decrypt.

2. **Data volume** — `docker-compose.prod.yml` declares `nb-data` as
   `external: true` so a stray `docker compose down -v` cannot delete live data.
   Create it once:
   ```bash
   docker volume create nb-data
   ```

3. **TLS material** in `/etc/northbound/tls/`, issued by the local step-ca:
   `cert.pem`, `key.pem` (readable by uid 10001 — the container's `app` user),
   `root_ca.crt`. Renewal runs from `northbound-cert-renew.timer`.

4. **Healthcheck script**:
   ```bash
   install -m 644 deploy/healthcheck.py /etc/northbound/healthcheck.py
   ```
   Required because the image's baked-in HEALTHCHECK probes plain HTTP and
   would report a false "unhealthy" against the TLS port.

5. **443 → 8090 redirect** — `northbound-443-redirect.service`.
   **Both** the PREROUTING and OUTPUT rules must be scoped with `-d <host-ip>`.
   An unscoped PREROUTING rule also matches traffic *originating in containers*
   (it arrives on `docker0` and traverses PREROUTING), which silently breaks
   outbound HTTPS for every container on the box — including `pip` during
   `docker build`.

## Known host hazard: VPN vs the Docker bridge

A VPN on this node pushes a route for `172.17.0.0/16` — Docker's default bridge
subnet — via `tun0`. Container replies then route into the tunnel instead of
back to `docker0`, and **all bridge networking silently times out**. Symptoms:
`docker build` fails with pip "Temporary failure in name resolution", and
containers cannot reach even the host's own IP.

Check with:

```bash
ip route show table all | grep 172.17
```

Two mitigations, both already in place or recommended:

- Builds pass `--network=host` (already in `make docker-build` and the
  `build.network: host` key in `docker-compose.prod.yml`).
- The app itself runs `network_mode: host`, so its runtime is unaffected.
- **Permanent fix**: move Docker's bridge off the colliding range in
  `/etc/docker/daemon.json`, e.g. `{"bip": "172.31.0.1/16"}`, then restart
  docker. Do this during a maintenance window — it restarts every container.
