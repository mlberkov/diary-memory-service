# Self-hosted Deployment Roadmap — DEPLOY-1

## Purpose & status

This document is the refinable-sequence companion to **D-060** (DEPLOY-1.1). It
decomposes the first implemented reference deployment shape — **DEPLOY-1: a
self-hosted VPS + Telegram contour for a single-community pilot** — into an
ordered set of bounded follow-up packets, and records the deferred
**DEPLOY-2** managed-cloud reference deployment as the second peer shape.

**Status: DEPLOY-1.1 landed (D-060) — decision + roadmap. DEPLOY-1.2 landed
(D-061) — VPS runtime shape (Dockerfile + docker-compose `vps` profile;
opt-in via `docker compose --profile vps up`). DEPLOY-1.3..1.x are not
started.**

This mirrors the D-042 / `docs/RENAMING-ROADMAP.md` and D-044 /
`docs/OPERATIONALIZATION-ROADMAP.md` precedent: the decision entry (D-060)
carries the stable contract; this doc carries the refinable sequence and is the
operator/developer-facing summary. **D-060 stays authoritative** for the
invariants and current defaults; this doc mirrors them so they are easy to read
alongside the sequence, but does not re-decide them.

---

## 1. Scope

DEPLOY-1 = the self-hosted VPS + Telegram contour for a single-community pilot.
DEPLOY-2 (managed-cloud reference deployment) is **deferred** and lives only as
a forward pointer here; D-026 / D-027 peer parity across self-hosted OSS,
managed cloud, and embedded shapes is preserved by D-060 and is not re-litigated
here.

### Explicitly out of scope

- Anything inside the managed-cloud peer shape (DEPLOY-2 — reopens A-41).
- Anything inside the embedded peer shape.
- Re-deciding the OP-4 WAL/base-backup primitives; the DEPLOY-1 off-box backup
  sink packet **wires** them off-box, it does not re-decide them.

---

## 2. DEPLOY-1 invariants (mirrored from D-060)

Cannot change without a new decision packet:

- **OS family:** Debian / Ubuntu LTS.
- **Tenancy:** single-community / single-tenant default for the first pilot.
- **Reachability:** public DNS + HTTPS required (not optional).
- **Raw-data durability:** off-box backup destination required (S3-compatible
  or equivalent); a local-only backup is not sufficient.
- **Operator model:** an operator-facing, idempotent install/upgrade script
  that can bring a clean VPS from zero to a working deployment and upgrade it
  later with a clear status outcome.

## 3. DEPLOY-1 current defaults (mirrored from D-060)

Revisable in DEPLOY-1.x as long as the invariants above remain intact. A
revision must surface itself either as a small follow-up decision-log note or
as the revising packet's docs update explicitly naming the default it revises:

- **Reverse proxy / TLS terminator** — candidate set: Caddy / nginx / other
  ACME-capable proxy. Pinned in the proxy packet (§4).
- **Backup tool** — candidate set: restic / custom scripts around rclone /
  `pg_dump` / `pg_basebackup`. Pinned in the backup-sink packet (§4).
- **Installer implementation** — bash vs Python CLI; interactive vs
  non-interactive UX. Pinned in the installer packet (§4).

**Default-stability mitigation.** The installer packet must design a
configuration-versioning seam and a documented upgrade path so a later
DEPLOY-1.x packet can swap any of the three defaults above without rewriting
the installer. This is a packet-design constraint on the installer packet, not
a deliverable of DEPLOY-1.1.

---

## 4. DEPLOY-1.x packet sequence (refinable)

The packets below express the contour signals D-060 commits to. **Names,
exact granularity, and ordering between independent packets are refinable when
each packet is planned** — they may be merged or split as long as every
resulting packet preserves the invariants in §2 and cites "operates within
DEPLOY-1 invariants — A-22 updated by D-060".

| Packet | Surfaces it touches | Status |
| --- | --- | --- |
| **DEPLOY-1.1 — decision + roadmap** | This doc; D-060; `assumptions.md` (A-22 closed / A-41 deferred / A-42 / A-43); `execution-map.md`; `todo.md`; `RUNBOOK.md`; `OPERATIONALIZATION-ROADMAP.md` (see-also); `BuildPlan.md` (target-state shape). Docs-only. | **Landed (D-060).** |
| **DEPLOY-1.2 — VPS runtime shape** | `Dockerfile` + a docker-compose `vps` profile (opt-in: `docker compose --profile vps up`) — `app_init` one-shot for OP-1 migrations + `app` running uvicorn behind FastAPI, both gated by `profiles: ["vps"]` — bringing the app and OP-1 / OP-4-shaped Postgres up on a clean Debian / Ubuntu LTS VPS. App port loopback-only until DEPLOY-1.3. No proxy, no installer wrapping yet. | **Landed (D-061).** |
| **DEPLOY-1.3 — reverse-proxy + TLS contour** | The proxy / TLS terminator default (§3) plus ACME automation in front of the VPS runtime. Pins the proxy default. | To be planned. Depends on DEPLOY-1.2. |
| **DEPLOY-1.4 — installer / upgrade script** | Operator-facing, idempotent install/upgrade script bringing a clean VPS to a working deployment and upgrading it later with a clear status outcome. Pins the installer default and designs the configuration-versioning seam + documented upgrade path mitigation (§3). | To be planned. Depends on DEPLOY-1.2 and DEPLOY-1.3. |
| **DEPLOY-1.5 — Telegram webhook registration automation** | Operator-driven registration of the Telegram webhook against the public DNS contour established by DEPLOY-1.3, wired into the installer's status outcome. | To be planned. Depends on DEPLOY-1.3 and DEPLOY-1.4. |
| **DEPLOY-1.6 — off-box backup sink wiring** | Operator-side wiring of the OP-4 WAL / base-backup primitives to the off-box destination required by §2 (S3-compatible or equivalent). Pins the backup-tool default. Re-uses OP-4 outputs; does not re-decide them. May fold in a logs-first observability scope for the first VPS contour — see A-43. | To be planned. Depends on DEPLOY-1.2. |
| **DEPLOY-1.7 — end-to-end smoke + drill** | Clean-VPS → working-pilot smoke and a one-shot upgrade drill exercising DEPLOY-1.2..1.6. Closes DEPLOY-1. | To be planned. Depends on DEPLOY-1.2..1.6. |
| **DEPLOY-2 — managed-cloud reference deployment** *(deferred)* | The managed-cloud peer shape. Resolves A-41. Has its own roadmap doc when it is pulled. | **Deferred** — no near-term operator. |

---

## 5. Dependencies & ordering rationale

```
DEPLOY-1.1 ──▶ DEPLOY-1.2 ──┬──▶ DEPLOY-1.3 ──▶ DEPLOY-1.4 ──▶ DEPLOY-1.5 ──▶ DEPLOY-1.7
                            └──▶ DEPLOY-1.6 ────────────────────────────────────▶
```

- **DEPLOY-1.2 first** — the proxy / installer / webhook / backup-sink packets
  all need a runnable VPS runtime to terminate against.
- **DEPLOY-1.3 ≺ DEPLOY-1.4 ≺ DEPLOY-1.5** — the installer wraps the
  proxy contour, and webhook registration needs the public DNS the proxy
  contour establishes.
- **DEPLOY-1.6 independent of DEPLOY-1.3..1.5** — off-box backup wiring only
  needs DEPLOY-1.2's Postgres + OP-4 primitives; it may run in parallel with
  the proxy / installer / webhook line.
- **DEPLOY-1.7 closes DEPLOY-1** — the smoke + drill is the only packet that
  exercises every other DEPLOY-1.x packet end to end.

---

## 6. Exit criterion

DEPLOY-1 exits when a clean Debian / Ubuntu LTS VPS can be brought from zero to
a working single-community Telegram-bound pilot through the operator-facing
idempotent install/upgrade script (DEPLOY-1.4), with public DNS + HTTPS in
place (DEPLOY-1.3), the webhook registered against that public surface
(DEPLOY-1.5), off-box backups verified against the OP-4 primitives
(DEPLOY-1.6), and the clean-VPS → pilot → upgrade smoke + drill green
(DEPLOY-1.7).

---

## See also

- **D-060** in `docs/decision-log.md` — the authoritative decision entry for
  the DEPLOY-1 invariants, current defaults, and the DEPLOY-2 deferral.
- **A-22 (closed → D-060), A-41 (open, deferred until DEPLOY-2), A-42, A-43**
  in `docs/assumptions.md` and `docs/assumption-audit.md`.
- **D-026, D-027** in `docs/decision-log.md` — the peer-parity rule D-060
  preserves.
- `docs/OPERATIONALIZATION-ROADMAP.md` — the structurally analogous Stage-2
  roadmap doc (now complete) and the source of the OP-4 backup / restore
  primitives DEPLOY-1.6 reuses.
- `docs/RENAMING-ROADMAP.md` — the precedent for "decision entry carries the
  stable contract, roadmap doc carries the refinable sequence".
- `docs/execution-map.md` — the deployment-shape rollout section with
  DEPLOY-1.x placeholder rows pointing here.
- `docs/todo.md` — the DEPLOY-1 backlog section.
- `docs/RUNBOOK.md` — the "Self-hosted VPS reference shape (DEPLOY-1 / D-060)"
  section.
