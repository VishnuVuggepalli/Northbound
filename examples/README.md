# examples/

Copy-paste-ready inputs for Northbound. Nothing here is loaded by the app — these
are samples you adapt and send (or use as a config starting point).

## Config

The documented config templates live at the repo root, not here:

- `../config.example.toml` — every setting with comments
- `../.env.example` — the env vars (secrets) for a container/systemd deploy

## API request payloads (`requests/`)

JSON bodies for the change-request endpoints. Each is the exact shape the API
validates (Pydantic). Send them after logging in (see
[`../share/api-walkthrough.sh`](../share/api-walkthrough.sh) for the full flow).

| File | Endpoint | What it does |
|---|---|---|
| `requests/port-vlan-change.json` | `POST /api/requests` | Move a switchport's untagged + tagged VLANs |
| `requests/vlan-create.json` | `POST /api/requests/vlan` | Create a VLAN in the device's VLAN database |
| `requests/l3-svi-create.json` | `POST /api/requests/l3` | Create an SVI (VLAN interface) with an IPv4 address |
| `requests/vrf-create.json` | `POST /api/requests/vrf` | Create a VRF |
| `requests/ospf-interface.json` | `POST /api/requests/ospf` | Put an interface into an OSPF area |
| `requests/comment.json` | `POST /api/requests/{id}/comments` | Post a comment on a request's thread |

> Replace `device_id` with a real id from `GET /api/devices`. IPs in the samples
> are RFC 5737 documentation ranges (`192.0.2.0/24`) — safe, non-routable.
