# Self-hosted Deployment Roadmap — DEPLOY-1

## Purpose & status

This document is the refinable-sequence companion to **D-060** (DEPLOY-1.1). It
decomposes the first implemented reference deployment shape — **DEPLOY-1: a
self-hosted VPS + Telegram contour for a single-community pilot** — into an
ordered set of bounded follow-up packets, and records the deferred
**DEPLOY-2** managed-cloud reference deployment as the second peer shape.

**Status: DEPLOY-1.1 landed (D-060) — decision + roadmap. DEPLOY-1.2 landed
(D-061) — VPS runtime shape (Dockerfile + docker-compose `vps` profile;
opt-in via `docker compose --profile vps up`). DEPLOY-1.3 landed (D-062) —
reverse-proxy + TLS contour (Caddy + ACME automation, gated by the same
`vps` profile). DEPLOY-1.4 landed (D-063) — installer / upgrade script
(bash, non-interactive) at `scripts/installer/deploy.sh`, carrying the
configuration-versioning seam (`INSTALLER_CONFIG_VERSION` + an
installer-owned `.installer-state.json`). DEPLOY-1.5 landed (D-064) —
Telegram webhook auto-registration folded into the installer flow, the
`--unregister-webhook` teardown subcommand, the first non-trivial use of
the D-063 configuration-versioning seam (`INSTALLER_CONFIG_VERSION=2` +
`migrate_v1_to_v2`), and the `webhook_registration` block in
`.installer-state.json`. DEPLOY-1.6..1.7 are not started.**

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

- **Reverse proxy / TLS terminator** — **Caddy** (pinned in DEPLOY-1.3 /
  D-062 from the candidate set Caddy / nginx / other ACME-capable proxy).
- **Backup tool** — candidate set: restic / custom scripts around rclone /
  `pg_dump` / `pg_basebackup`. Pinned in the backup-sink packet (§4).
- **Installer implementation** — **bash, non-interactive** (pinned in
  DEPLOY-1.4 / D-063 from the candidate set bash / Python CLI;
  interactive / non-interactive — the candidate set is preserved as the
  source).

**Default-stability mitigation (realized in DEPLOY-1.4 / D-063; first
non-trivial use in DEPLOY-1.5 / D-064).** The installer carries an
`INSTALLER_CONFIG_VERSION` constant in `scripts/installer/deploy.sh`
paired with an installer-owned `.installer-state.json` next to the repo
root (gitignored). The script compares the two views and applies named
`migrate_v<old>_to_v<new>` helpers in order; a deployed config newer than
the installer is refused without invoking `docker compose up`. Later
DEPLOY-1.x packets that swap or add a default (proxy / backup tool /
installer implementation) bump `INSTALLER_CONFIG_VERSION` and add a new
helper rather than rewriting the installer. DEPLOY-1.5 / D-064 is the
first packet to exercise the seam: it bumps the constant `1 → 2` and
appends `migrate_v1_to_v2` (a no-op stamp; the new
`webhook_registration` block in `.installer-state.json` is materialized
by the next `write_state_success` call). DEPLOY-1.6 will bump the
constant again when it pins the backup-tool default.

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
| **DEPLOY-1.3 — reverse-proxy + TLS contour** | A new `configs/caddy/Caddyfile` and a new `caddy` service in `docker-compose.yml` gated by `profiles: ["vps"]`, plus two new `.env.example` knobs (`PUBLIC_HOSTNAME`, `ACME_EMAIL`) and a new "Reverse-proxy + TLS contour (DEPLOY-1.3 / D-062)" subsection in `docs/RUNBOOK.md`. Pins **Caddy** as the §3 reverse-proxy / TLS terminator default. The DEPLOY-1.2 loopback `127.0.0.1:8000:8000` publish on `app` is retained as operator-only bypass-the-proxy inspection, not a closure signal. No `src/` change. | **Landed (D-062).** |
| **DEPLOY-1.4 — installer / upgrade script** | `scripts/installer/deploy.sh` — operator-facing, idempotent, non-interactive bash installer that wraps the canonical `docker compose --profile vps up -d --build` bring-up with preflight, a state-machine driven by `.installer-state.json` + `INSTALLER_CONFIG_VERSION` (the configuration-versioning seam realized here), and an honest status outcome that distinguishes the mandatory loopback `/health` probe from the best-effort public-TLS probe. Pins **bash, non-interactive** as the §3 installer-implementation default. Also adds `.installer-state.json` / `.installer-state.last_failure.json` `.gitignore` entries and a new `docs/RUNBOOK.md` "Installer / upgrade script (DEPLOY-1.4 / D-063)" subsection. No `src/` / schema / migration / `docker-compose.yml` change. | **Landed (D-063).** |
| **DEPLOY-1.5 — Telegram webhook registration automation** | `scripts/installer/deploy.sh` — `register_telegram_webhook` helper folded into the canonical install path (best-effort, mirrors `public_tls_probe` semantics); new `--unregister-webhook` subcommand; `webhook_registration` block in `.installer-state.json`; `INSTALLER_CONFIG_VERSION` bumped `1 → 2` with `migrate_v1_to_v2` (first non-trivial use of the D-063 seam); `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` joined the preflight required-env set. No `src/` / schema / migration / `docker-compose.yml` / `.env.example` change. New "Telegram webhook registration (DEPLOY-1.5 / D-064)" subsection in `docs/RUNBOOK.md`. | **Landed (D-064).** |
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
