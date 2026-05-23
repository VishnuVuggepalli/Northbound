# Northbound — Product Manager View

> Companion to `plan.md`. This is the PM lens: who, why, what wins, what doesn't ship.

## The real problem (behind the problem)

**Surface ask:** "stop interrupting me with port questions."

**Real problem:** the network engineer's deep work is fragmented. Each interrupt costs ~23 minutes of context, and the SDN roadmap is the casualty. Northbound's job isn't to be a NMS — it's to **buy back engineer hours so SDN ships**.

If we deliver a beautiful tool that doesn't move the interrupt count, we failed.

## Users & jobs-to-be-done

| User | Count | Job |
|---|---|---|
| **Avery (engineer, admin)** | 1 | Stay in flow. Stop being a Slack lookup service. Apply changes safely. Audit who did what. |
| **Colleague (requester)** | ~10 | Get an answer to "what's on port X" in 5 seconds. File a port change without learning networking. |
| **Future-Avery (postmortem)** | 1 | Know who changed what, when, in <30 seconds. |

**Primary JTBD:** *"When my new server is racked, I want to know what VLAN/port it lands on without interrupting Avery, so I can finish provisioning."*

**Secondary JTBD:** *"When a request comes in, I want to see the diff and one-click approve, so I keep flow."*

## Metrics

### North star
**Direct interrupts/week to engineer about port state.** Target: **↓80% in 4 weeks** of MVP-A launch.

Track by hand for 4 weeks pre-launch as baseline. Without baseline, no claim of victory.

### Lead indicators
- % port questions self-served in UI vs. asked in chat
- Median engineer-touch-time per change request (target <30s)
- % applied changes reverted within 24h (trust signal, target <2%)
- Weekly active requesters / total colleagues
- Onboarding time-to-first-value (target <5 min from login → live ports visible)
- # support questions about onboarding (target: 0)

## Roles

Two roles, hardcoded:

- **admin** — full read + write. Edit port metadata, approve/reject requests, push config, manage users, onboard devices.
- **requester** — full read across everything. Submit change requests. See own request status. No direct edit.

UI is **identical for both roles**. Admin-only buttons appear inline rather than behind a separate panel.

### Hard policy
**`role in (router, vpn)` devices are read-only forever, no admin override.** Defense in depth: enforced at driver, API, DB, and UI layers. Includes FreeBSD routers and the VPN node.

## MVP cuts (outcome-flavored)

Outcomes, not phases. Each unlocks the next.

| Cut | Outcome | Time |
|---|---|---|
| **M1 — Read directory** | Avery onboards his switches in <5 min each. Colleagues see live state. Avery stops getting Slack-pinged for "what's on port X." | wk 2 |
| **M2 — Request inbox** | Colleagues file 80% of changes via portal. Avery still pushes via CLI. Diff view + audit. | wk 4 |
| **M3 — One-click apply (lab MikroTik)** | Lab changes auto-pushed with backup. Per-device write toggle. | wk 6 |
| **M4 — DC drivers** | Arista + Pica8 included. FreeBSD stays read-only forever. | wk 10 |
| **M5 — Polling + nightly backup** | Always-fresh reachability. DR safety net. | wk 11 |

**MVP-A alone moves the north-star metric.** Don't build M2–M5 if M1 doesn't ship and get used.

## Trust ladder

Don't unlock the next rung until previous one's been clean for one week of real use.

1. Read-only (M1) — earn the right to write
2. Manual apply, request shows diff (M2)
3. One-click apply, **lab MikroTik only** (M3)
4. Lab-wide all writable platforms
5. DC Arista
6. DC Pica8
7. **FreeBSD writes — never. Hard policy.**

Each rung gates on a week of zero incidents. Ship via per-device feature flags, not per-platform.

## Onboarding (the first impression)

Onboarding isn't a setup step. It's the product's first impression. Avery's first 10 minutes must end with him seeing live ports of his first switch — no YAML, no restarts.

### Time-to-first-value target
**< 5 min** from "create admin account" to "see live ports of first switch."

### UX principles
1. **No YAML, no config files, no service restart.** If we can't do it in the UI, we don't do it in v1.
2. **Test before save.** Every wizard step validates against the real device before persisting.
3. **Show what we found.** Discovery step shows preview of ports + config. No black-box confirms.
4. **Reversible.** Every onboarded device can be edited or removed. No tombstones, no orphans.
5. **One device at a time.** No bulk import. Forces clarity, prevents copy-paste credential leaks.

### Trust ladder for onboarding (mirrors apply trust ladder)
1. **Preview mode** — paste creds, see ports once, nothing stored. Avery validates.
2. **Stored read-only** — creds saved, polling enabled, no writes possible.
3. **Stored writable** — apply flow unlocks per-device after burn-in.

### Success criteria (definition of done for M1's onboarding piece)
- [ ] Avery onboards a switch in <5 min, no docs needed
- [ ] Wrong creds → clear error, retry in same wizard, no DB pollution
- [ ] After confirm, ports visible within 10 seconds
- [ ] No support ping needed during a self-onboarding by a colleague who's never seen the app

## Integrations — Track 2 (secondary)

Switches are the spine (Track 1). Zoho integrations are Track 2 — they start only after M1 ships and is being used. If Track 1 slips, Track 2 freezes.

### Cliq (first-class chat surface)

Tier-ranked by north-star impact:

| Feature | Impact | Tier |
|---|---|---|
| `/nb port <device> <port>` slash lookup | ★★★ — colleagues never open portal for "what's on port X" | M1 stretch |
| Interactive approval bot DM (buttons: Approve & Apply / Reject) | ★★★ — kills engineer-touch-time | M2/M3 |
| `#northbound` channel notifications (applied, unreachable, daily digest) | ★★ | M2 |
| `/nb-tip` redirect snippet for Avery to fire on incoming DMs | ★★ — adoption catalyst | M1 stretch |
| Auto-listen on Avery's DMs | ❌ creepy, never | — |

### Email (Zoho Mail) — formal record layer

| Feature | Tier |
|---|---|
| Outbound: applied receipt to requester | M2 |
| Outbound: failure alert to requester + admin | M2 |
| Outbound: daily digest to admin | M2 |
| Inbound: parse `[NB] device port -> VLAN N` template → request | M3 (defer until adoption proves it's needed) |
| LLM fallback parser for free-form emails | Later |
| Real-time per-event email to admin | Never (Cliq does this better) |

### Zoho Projects mirror — deferred

One-way mirror NB request → Zoho task. Defer until Avery says "I want sprint planning to live in Zoho." Two-way sync = drift hell, never.

## Channel split

| Surface | Role | Latency |
|---|---|---|
| **Cliq** | Ops loop. Where Avery + colleagues already live. Real-time, interactive. | Seconds |
| **Email (Zoho Mail)** | Formal record. Receipts. Audit-friendly. | Minutes |
| **Portal (Northbound UI)** | Truth. 3D view, full diff, history, deep dives. | On demand |

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Colleagues keep DM'ing Avery anyway | High | 2-week redirect campaign. `/nb-tip` snippet. |
| First bad VLAN push → trust collapse | High | Lab-first, mandatory backup-before-push, commit-confirm where supported, dry-run default. |
| Stale 30s cache → request based on wrong state | Med | Fingerprint state at file-time, re-validate at apply, refuse on drift. |
| Scope creep into IPAM/inventory | Med | Hard NO list. Every PR rejected if touches. |
| Avery bus factor | Med | Audit log + README = onboarding doc for replacement. |
| Avery fails first-onboarding | High | Per-platform inline help, "Test connection" with verbose error. |
| He pastes prod creds into untrusted tool | High | Preview mode option (one-shot, nothing stored) before promoting to stored. |
| Cred leak via logs | Catastrophic | Redact at log layer. Audit excludes plaintext cred field. |
| Cliq webhook spoofed | High | HMAC signature verify, mandatory. |
| Cliq down → no approvals possible | Low | Portal still works as fallback. |

## Ecosystem positioning (added after open-source tool survey)

Northbound is a **request-mediated port-change workflow**. It is NOT:

- **A monitoring/alerting platform** — use LibreNMS, Observium, Prometheus + Grafana
- **A bulk config push tool** — use Ansible, MikroWizard, Napalm
- **A network source-of-truth / intent model** — use NetBox, Nautobot
- **A multi-vendor abstraction layer** — Northbound has direct drivers for 5 platforms; Napalm is overkill at this scale
- **A firmware update orchestrator** — out of scope forever

It **complements** those tools. Run LibreNMS for graphs + alerts; run Northbound for "Alice needs port 14 on VLAN 200, here's the diff, click apply, done in 30 seconds."

This paragraph ships in the README v0 and on the in-app `/about` page. Sets expectations day 1 and answers 60% of "why doesn't Northbound do X?" questions in advance.

## SwOS scope (decided after vendor research)

MikroTik SwOS is a different product line from RouterOS — different API surface, different capabilities. Decision:

**Option B selected: SwOS read-only via SNMP + HTTP scrape (backup-only).**

Rationale:
- Colleagues asking "what's on SwOS port X?" get answered → moves north-star metric
- Writes blocked at driver layer (`writable=False`) — explicit, defensible, "use SwOS web UI for changes"
- SwOS SNMP MIBs are well-supported (IF-MIB, BRIDGE-MIB, MIKROTIK-MIB) — read path is vendor-supported
- ~2 days work; mostly identifying the right MIBs

SwOS write attempts via HTTP scrape are **never** in scope — firmware-bump fragility is real and unacceptable for ops trust.

## Hard NO list (anti-features)

Tempting; would fragment the product. Reject every time:

- IPAM, host inventory, rack/cable modeling
- Monitoring/alerting (use existing tools — see Ecosystem positioning above)
- Multi-tenancy
- Auto-discovery of devices (subnet scan)
- **LLDP-driven auto-onboarding** — LLDP info displayed only, never used to register devices automatically
- Mobile app
- External public REST API / webhooks
- Analytics dashboard
- Bulk operations (one device, one port at a time)
- Scheduled changes ("apply at 2am")
- **FreeBSD writes** — never
- **SwOS writes** — never (read-only via SNMP only)
- **SNMP-set for any config change** — half-supported across platforms, fragile
- Multi-vendor abstraction lib (Napalm, NAPALM-automation)
- **Iframe-embedded vendor UIs** (deep-link in new tab instead)
- Two-way Zoho Projects sync
- In-app comment threads (Cliq exists)
- Bulk CSV device import
- Pre-shipped vendor configs
- Auto-listen DM bot ("creepy mode")

## Dogfood plan

- Week 1 of M1: Avery solo, lab only
- Week 2: invite 2 closest colleagues, fix friction
- Week 3: open to whole team
- Reverse-canary: any incident → flag flips back, rung locks

Track interrupt count by hand for 4 weeks before launch + 4 after to prove north-star.

## Open product decisions

1. **Preview mode** during onboarding (one-shot creds, nothing stored) — yes/no for v1?
2. **Per-device write toggle UX** — default off (trust ladder) or default on (faster value)?
3. **Day-1 empty state** — guided tour or just "Add device" CTA?
4. **Email digest cadence** — daily 9am? Real-time per-event? Hybrid?
5. **Tier 2 Cliq commands** — ship with M1 (read-only `/nb port`) or wait until M2?
6. **SwOS lab fixtures** — do we have a reachable SwOS device to record SNMP-walk + HTTP-scrape fixtures from, or do we generate synthetic fixtures from MIB definitions?
7. **LLDP scope** — display `chassis_id`, `port_id`, `system_name` only, or also `mgmt_address`? Adding mgmt_address opens the door to "click neighbor → onboard it" later. Recommend defer; display only the basics now.
