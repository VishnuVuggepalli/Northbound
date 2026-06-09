# Getting started with Northbound

Northbound mediates network config changes through a **request → review → apply**
workflow, with backup, audit, and rollback on every change.

## 1. Log in

Open the app (e.g. `http://<host>:8090`) and sign in. Two users are seeded on
first boot:

| User | Role | Can |
|---|---|---|
| `admin` | admin | review, approve/request-changes, **apply** changes |
| `alice` | requester | file requests, comment, resubmit |

Passwords come from `NB_SEED_ADMIN_PASSWORD` / `NB_SEED_ALICE_PASSWORD` (or a
random admin password printed once in the logs on first seed).

## 2. The request lifecycle

```
        file            approve           apply           confirm*
PENDING ─────▶ PENDING ────────▶ APPROVED ──────▶ AWAITING_CONFIRM ──────▶ APPLIED
   │              │                                      │
   │              ▼ request-changes                      ▼ (commit-confirm
   │         NEEDS_REVISION ──resubmit──▶ PENDING         platforms only)
   ▼ reject
REJECTED
```

- **File** — a requester describes the change (a port move, or a VLAN / SVI /
  loopback / VRF / OSPF object). The app renders the exact device diff.
- **Review** — an admin sees the diff and either **approves**, **rejects**, or
  **requests changes** (a soft bounce with a reason, → `NEEDS_REVISION`).
- **Resubmit** — the requester edits and resubmits; this **re-captures the drift
  baseline**, so a request that went stale starts fresh.
- **Apply** — the admin applies. The driver pushes config to the device. On
  commit-confirm platforms (Arista, Cisco) the change lands in a confirm window
  and must be **confirmed** or it auto-reverts.

## 3. Talk it out — the comment thread

Every request has a thread (transitions **and** free-text comments in one
timeline). Both sides comment; it updates live over SSE — no refresh. Use it to
clarify scope before applying instead of rejecting outright.

## 4. State-drift guard

When a request is filed, Northbound fingerprints the **target port's** current
VLAN state. At apply time it re-checks: if that port changed since filing, the
apply is **blocked (409)** so a human re-confirms. Fix: **edit & resubmit** to
re-baseline, then apply. (Drift is scoped per-port — an unrelated edit elsewhere
on the device won't block your request.)

## 5. When a change is out of scope

Complex/vendor-specific changes Northbound doesn't model: every device surface
has an **"Open in vendor UI"** button to the device's own web UI. No dead ends.

## Next: drive it from the API

See [`api-walkthrough.sh`](api-walkthrough.sh) for a full curl flow, and
[`../examples/requests/`](../examples/requests/) for ready-made payloads.
