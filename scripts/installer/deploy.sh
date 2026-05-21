#!/usr/bin/env bash
# DEPLOY-1.4 / D-063 — operator-facing idempotent install / upgrade script
# for the self-hosted VPS reference deployment. Operates within DEPLOY-1
# invariants — A-22 updated by D-060.
#
# Wraps the canonical bring-up `docker compose --profile vps up -d --build`
# (DEPLOY-1.2 / D-061 + DEPLOY-1.3 / D-062) with:
#   - non-interactive preflight against the operator-filled .env;
#   - state-machine driven by .installer-state.json + INSTALLER_CONFIG_VERSION
#     (the D-060 configuration-versioning seam — a later DEPLOY-1.x packet
#     bumps INSTALLER_CONFIG_VERSION and adds a migrate_v<old>_to_v<new>
#     helper when it swaps or adds a default);
#   - honest status outcome that distinguishes the mandatory loopback /health
#     probe from the best-effort public-TLS probe — loopback /health is
#     operator-only bypass-the-proxy inspection per DEPLOY-1.3 / D-062 and is
#     NOT public-TLS closure evidence on its own; the decisive clean-VPS
#     pilot smoke is DEPLOY-1.7's responsibility.
#
# DEPLOY-1.5 / D-064 extends the install path with best-effort Telegram
# webhook auto-registration against the public-TLS contour and adds the
# `--unregister-webhook` teardown subcommand. INSTALLER_CONFIG_VERSION bumps
# 1 → 2 with a new `migrate_v1_to_v2` no-op stamp.
#
# DEPLOY-1.6 / D-065 extends the install path with a best-effort off-box
# backup-sink probe against the operator-supplied S3-compatible target,
# pins the §3 backup-tool default to `rclone`, and adds the new
# `offbox_backup_probe` field to `.installer-state.json`.
# INSTALLER_CONFIG_VERSION bumps 2 → 3 with a new `migrate_v2_to_v3` no-op
# stamp (the new state-file shape — `selected_defaults.backup_tool="rclone"`
# plus the `offbox_backup_probe` field — is materialized by the next
# `write_state_success` call, mirroring the D-064 precedent).
#
# Single canonical operator command: ./scripts/installer/deploy.sh
# See docs/RUNBOOK.md "Installer / upgrade script (DEPLOY-1.4 / D-063)",
# "Telegram webhook registration (DEPLOY-1.5 / D-064)", and "Off-box
# backup sink (DEPLOY-1.6 / D-065)".

set -eu

INSTALLER_CONFIG_VERSION=3

STATE_FILE_NAME=".installer-state.json"
FAILURE_FILE_NAME=".installer-state.last_failure.json"

# Required keys for the vps-profile public-TLS contour
# (DEPLOY-1.3 / D-062) plus the Telegram pilot credentials the DEPLOY-1.5 /
# D-064 webhook-registration path needs to call setWebhook.
REQUIRED_ENV_KEYS="POSTGRES_PASSWORD PUBLIC_HOSTNAME ACME_EMAIL TELEGRAM_BOT_TOKEN TELEGRAM_WEBHOOK_SECRET"

# Set later by resolve_repo_root.
REPO_ROOT=""

usage() {
  cat <<'USAGE'
usage: deploy.sh [--check | --status | --version | --unregister-webhook | --help]

  (none)                Install or upgrade depending on .installer-state.json
                        state. The canonical operator command. Non-interactive:
                        reads .env; runs
                        `docker compose --profile vps up -d --build`; probes
                        loopback /health (mandatory) and public-TLS /health
                        (best-effort); registers the Telegram webhook against
                        the public-TLS contour (best-effort, DEPLOY-1.5 /
                        D-064); probes the off-box backup sink against the
                        operator-supplied S3-compatible target (best-effort,
                        DEPLOY-1.6 / D-065); writes .installer-state.json on
                        success.
  --check               Preflight only. Reads inputs, writes nothing. Exit 0
                        if all preconditions are satisfied; non-zero with
                        diagnostics otherwise.
  --status              Print the current .installer-state.json (or
                        "not installed" if absent). Exits 0.
  --version             Print INSTALLER_CONFIG_VERSION. Exits 0.
  --unregister-webhook  Call Telegram deleteWebhook against the bot token in
                        .env, then clear the webhook_registration block in
                        .installer-state.json (DEPLOY-1.5 / D-064). Exits 0
                        on success, non-zero on Telegram or filesystem error.
  --help                Print this usage.

Documented in docs/RUNBOOK.md "Installer / upgrade script (DEPLOY-1.4 / D-063)",
"Telegram webhook registration (DEPLOY-1.5 / D-064)", and "Off-box backup sink
(DEPLOY-1.6 / D-065)".
USAGE
}

now_utc_iso() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

# Walk up from this script's location until we find Dockerfile +
# docker-compose.yml + pyproject.toml co-located. Refuse otherwise so the
# installer never operates on an unintended directory.
resolve_repo_root() {
  script_dir=$(cd -- "$(dirname -- "$0")" && pwd -P)
  candidate="${script_dir}"
  while [ "${candidate}" != "/" ]; do
    if [ -f "${candidate}/Dockerfile" ] \
        && [ -f "${candidate}/docker-compose.yml" ] \
        && [ -f "${candidate}/pyproject.toml" ]; then
      REPO_ROOT="${candidate}"
      return 0
    fi
    candidate=$(dirname -- "${candidate}")
  done
  echo "deploy.boot.error could not locate repo root (Dockerfile + docker-compose.yml + pyproject.toml co-located) from $0" >&2
  exit 1
}

state_path() {
  printf '%s/%s' "${REPO_ROOT}" "${STATE_FILE_NAME}"
}

failure_path() {
  printf '%s/%s' "${REPO_ROOT}" "${FAILURE_FILE_NAME}"
}

# Read a single key from .env. The matcher is intentionally minimal: matches
# leading-whitespace KEY=value, skips lines whose first non-space is `#`,
# and prints everything to the right of the first `=`. Missing keys and
# empty values both surface as the empty string.
read_env_value() {
  key="$1"
  env_file="${REPO_ROOT}/.env"
  awk -F= -v k="${key}" '
    /^[[:space:]]*#/ { next }
    {
      lhs = $1
      sub(/^[[:space:]]+/, "", lhs)
      sub(/[[:space:]]+$/, "", lhs)
      if (lhs == k) {
        v = substr($0, index($0, "=") + 1)
        print v
        exit
      }
    }
  ' "${env_file}"
}

# Preflight: docker + compose v2 + repo-root + .env exists + required keys
# non-empty. On failure, prints `deploy.preflight.error ...` to stderr and
# exits 1. The caller decides whether to also write a failure marker (the
# install path does; the --check path does not, per the plan).
preflight() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "deploy.preflight.error docker not found on PATH; install Docker per docs/RUNBOOK.md preconditions" >&2
    return 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "deploy.preflight.error docker compose v2 plugin not available; legacy docker-compose v1 is unsupported" >&2
    return 1
  fi
  if [ ! -f "${REPO_ROOT}/.env" ]; then
    echo "deploy.preflight.error missing .env at ${REPO_ROOT}/.env — copy .env.example and fill the operator knobs (see docs/RUNBOOK.md)" >&2
    return 1
  fi
  missing=""
  for key in ${REQUIRED_ENV_KEYS}; do
    v=$(read_env_value "${key}")
    if [ -z "${v}" ]; then
      if [ -z "${missing}" ]; then
        missing="${key}"
      else
        missing="${missing} ${key}"
      fi
    fi
  done
  if [ -n "${missing}" ]; then
    echo "deploy.preflight.error .env is missing or empty for required keys: ${missing} — fill them (see docs/RUNBOOK.md)" >&2
    return 1
  fi
  return 0
}

# Read installer_config_version from .installer-state.json. Empty if absent
# or unparseable. No jq dependency — a portable awk match is sufficient
# because the file is installer-owned and always emitted by this script.
read_state_version() {
  path=$(state_path)
  [ -f "${path}" ] || return 0
  awk '
    match($0, /"installer_config_version"[[:space:]]*:[[:space:]]*[0-9]+/) {
      s = substr($0, RSTART, RLENGTH)
      n = s
      sub(/.*:[[:space:]]*/, "", n)
      print n
      exit
    }
  ' "${path}"
}

# Read a top-level scalar JSON string field from .installer-state.json.
# Empty if absent, null, or the file is missing. Only matches single-line
# `"key": "value"` rows — sufficient for the installer-owned shape this
# script always emits.
read_state_string() {
  key="$1"
  path=$(state_path)
  [ -f "${path}" ] || return 0
  awk -v k="${key}" '
    {
      pat = "\"" k "\"[[:space:]]*:[[:space:]]*\"[^\"]*\""
      if (match($0, pat)) {
        s = substr($0, RSTART, RLENGTH)
        sub(/.*:[[:space:]]*"/, "", s)
        sub(/"$/, "", s)
        print s
        exit
      }
    }
  ' "${path}"
}

# write_state_success <loopback> <public_tls> <webhook_status> <webhook_url> <offbox>
#
# <webhook_url> is the literal registered URL on a "registered (...)"
# status and the empty string for every other status; the writer emits
# JSON `null` in the empty case. <offbox> is the off-box backup-sink probe
# verdict — one of "ok", "skipped (...)", or "failed (...)" per
# probe_offbox_backup (DEPLOY-1.6 / D-065).
write_state_success() {
  loopback="$1"
  public_tls="$2"
  webhook_status="$3"
  webhook_url="$4"
  offbox="$5"
  ts=$(now_utc_iso)
  if [ -z "${webhook_url}" ]; then
    webhook_url_field="null"
  else
    webhook_url_field="\"${webhook_url}\""
  fi
  cat > "$(state_path)" <<EOF
{
  "installer_config_version": ${INSTALLER_CONFIG_VERSION},
  "selected_defaults": {
    "reverse_proxy": "caddy",
    "installer_impl": "bash",
    "backup_tool": "rclone"
  },
  "last_install_timestamp": "${ts}",
  "last_outcome": "success",
  "loopback_health": "${loopback}",
  "public_tls_probe": "${public_tls}",
  "offbox_backup_probe": "${offbox}",
  "webhook_registration": {
    "status": "${webhook_status}",
    "url": ${webhook_url_field},
    "attempted_at": "${ts}"
  }
}
EOF
  rm -f "$(failure_path)"
}

# write_state_unregistered — re-emit .installer-state.json with the
# webhook_registration block set to the "unregistered" shape, preserving
# the rest of the file. Reads existing fields via read_state_string;
# missing fields are written as null / empty so the file stays
# JSON-parseable.
write_state_unregistered() {
  path=$(state_path)
  [ -f "${path}" ] || return 0
  ts=$(now_utc_iso)
  prev_ts=$(read_state_string last_install_timestamp)
  loopback=$(read_state_string loopback_health)
  public_tls=$(read_state_string public_tls_probe)
  offbox=$(read_state_string offbox_backup_probe)
  [ -z "${prev_ts}" ] && prev_ts="${ts}"
  [ -z "${loopback}" ] && loopback="unknown"
  [ -z "${public_tls}" ] && public_tls="unknown"
  [ -z "${offbox}" ] && offbox="unknown"
  cat > "${path}" <<EOF
{
  "installer_config_version": ${INSTALLER_CONFIG_VERSION},
  "selected_defaults": {
    "reverse_proxy": "caddy",
    "installer_impl": "bash",
    "backup_tool": "rclone"
  },
  "last_install_timestamp": "${prev_ts}",
  "last_outcome": "success",
  "loopback_health": "${loopback}",
  "public_tls_probe": "${public_tls}",
  "offbox_backup_probe": "${offbox}",
  "webhook_registration": {
    "status": "unregistered",
    "url": null,
    "attempted_at": "${ts}"
  }
}
EOF
}

# write_failure <phase> <reason>
write_failure() {
  phase="$1"
  reason="$2"
  ts=$(now_utc_iso)
  # Escape backslashes and double quotes for valid JSON.
  escaped=$(printf '%s' "${reason}" | sed 's/\\/\\\\/g; s/"/\\"/g')
  cat > "$(failure_path)" <<EOF
{
  "installer_config_version_attempted": ${INSTALLER_CONFIG_VERSION},
  "phase": "${phase}",
  "reason": "${escaped}",
  "timestamp": "${ts}"
}
EOF
}

# No-op stamp on a fresh install. The state-file write itself records the
# v1 stamp. Future DEPLOY-1.x packets that swap or add a default append
# `migrate_v1_to_v2`, `migrate_v2_to_v3`, ... here and bump
# INSTALLER_CONFIG_VERSION accordingly; run_migrations applies them in
# order, lowest → highest.
migrate_to_v1() {
  return 0
}

# DEPLOY-1.5 / D-064 — v1 → v2 stamp. No-op: the new state-file shape (with
# the `webhook_registration` block) is materialized by the next
# `write_state_success` call. This helper exists so the appended-chain
# contract from D-063 is observable in the script.
migrate_v1_to_v2() {
  return 0
}

# DEPLOY-1.6 / D-065 — v2 → v3 stamp. No-op: the new state-file shape
# (`selected_defaults.backup_tool="rclone"` plus the `offbox_backup_probe`
# field) is materialized by the next `write_state_success` call. Mirrors
# the migrate_v1_to_v2 precedent — the seam is exercised by appending a
# named helper, not by rewriting the installer.
migrate_v2_to_v3() {
  return 0
}

# run_migrations <deployed_version>
run_migrations() {
  deployed="$1"
  if [ "${deployed}" -gt "${INSTALLER_CONFIG_VERSION}" ]; then
    msg="deployed config v${deployed} is newer than this installer v${INSTALLER_CONFIG_VERSION}; upgrade the installer before re-running"
    echo "deploy.upgrade.error ${msg}" >&2
    write_failure upgrade "${msg}"
    exit 1
  fi
  if [ "${deployed}" -lt 1 ]; then
    migrate_to_v1
  fi
  if [ "${deployed}" -lt 2 ]; then
    migrate_v1_to_v2
  fi
  if [ "${deployed}" -lt 3 ]; then
    migrate_v2_to_v3
  fi
  # When DEPLOY-1.x packets add migrate_v3_to_v4 etc., extend this chain.
}

bring_up_vps_profile() {
  ( cd "${REPO_ROOT}" && docker compose --profile vps up -d --build )
}

# Bounded retry: 15 attempts x 2s = up to 30s budget.
probe_loopback_health() {
  i=0
  while [ "${i}" -lt 15 ]; do
    if curl -fsS -o /dev/null "http://127.0.0.1:8000/health" 2>/dev/null; then
      printf 'ok'
      return 0
    fi
    i=$((i + 1))
    sleep 2
  done
  printf 'failed'
  return 0
}

# Returns one of: "ok", "failed", "skipped (PUBLIC_HOSTNAME unset)",
# "skipped (hostname did not resolve)". Best-effort — never fails the run
# on its own (clean-VPS pilot smoke is DEPLOY-1.7's responsibility).
probe_public_tls() {
  host=$(read_env_value PUBLIC_HOSTNAME)
  if [ -z "${host}" ]; then
    printf 'skipped (PUBLIC_HOSTNAME unset)'
    return 0
  fi
  if ! getent hosts "${host}" >/dev/null 2>&1; then
    printf 'skipped (hostname did not resolve)'
    return 0
  fi
  if curl -fsS -o /dev/null "https://${host}/health" 2>/dev/null; then
    printf 'ok'
  else
    printf 'failed'
  fi
}

# DEPLOY-1.5 / D-064 — register the Telegram webhook against the public-TLS
# contour. Returns one of:
#   "registered (https://<host>/telegram/webhook)"
#   "skipped (public_tls_probe=<value>)"
#   "failed (<short reason ≤200 chars>)"
# Bounded retry: 3 attempts × 2 s = up to 6 s budget. Best-effort — never
# fails the run on its own (mirrors public_tls_probe semantics). Telegram
# Bot API setWebhook is idempotent — a repeated call overwrites the prior
# URL and secret.
register_telegram_webhook() {
  public_tls="$1"
  if [ "${public_tls}" != "ok" ]; then
    printf 'skipped (public_tls_probe=%s)' "${public_tls}"
    return 0
  fi
  token=$(read_env_value TELEGRAM_BOT_TOKEN)
  secret=$(read_env_value TELEGRAM_WEBHOOK_SECRET)
  host=$(read_env_value PUBLIC_HOSTNAME)
  url="https://${host}/telegram/webhook"
  body=""
  i=0
  while [ "${i}" -lt 3 ]; do
    body=$(curl -fsS \
      --data-urlencode "url=${url}" \
      --data-urlencode "secret_token=${secret}" \
      "https://api.telegram.org/bot${token}/setWebhook" 2>/dev/null) || body=""
    case "${body}" in
      *'"ok":true'*)
        printf 'registered (%s)' "${url}"
        return 0
        ;;
    esac
    i=$((i + 1))
    [ "${i}" -lt 3 ] && sleep 2
  done
  reason=$(printf '%s' "${body}" | tr -d '\n' | cut -c1-200)
  if [ -z "${reason}" ]; then
    reason="setWebhook did not return ok:true within the 6s budget"
  fi
  printf 'failed (%s)' "${reason}"
  return 0
}

# DEPLOY-1.6 / D-065 — probe the operator-supplied off-box backup sink.
# Returns one of:
#   "ok"
#   "skipped (BACKUP_S3_BUCKET unset)"
#   "skipped (BACKUP_S3_ACCESS_KEY_ID unset)"
#   "skipped (BACKUP_S3_SECRET_ACCESS_KEY unset)"
#   "failed (<short reason ≤200 chars>)"
# Active probe via a one-shot `docker run --rm rclone/rclone:1.66 lsd`
# against the configured bucket — mirrors probe_public_tls's active shape so
# all three status variants are reachable. Two-step budget so a cold-pull
# of the rclone image does not consume the probe budget:
#   - pull step (only if image absent): `timeout 60 docker pull -q ...`,
#     best-effort — a pull failure is intentionally not fatal; the rclone
#     run that follows will surface a clean reason.
#   - probe step: `timeout 6 docker run --rm ... lsd offbox:${bucket}` —
#     same 6 s wall-clock budget as `register_telegram_webhook`. Subsequent
#     invocations skip the pull (image is cached) and only spend the 6 s.
# Best-effort — never fails the run on its own (clean-VPS off-box
# verification is DEPLOY-1.7's responsibility). Credentials are passed via
# `-e` env flags only; the operator's .env file is the credential source.
probe_offbox_backup() {
  bucket=$(read_env_value BACKUP_S3_BUCKET)
  if [ -z "${bucket}" ]; then
    printf 'skipped (BACKUP_S3_BUCKET unset)'
    return 0
  fi
  access_key=$(read_env_value BACKUP_S3_ACCESS_KEY_ID)
  if [ -z "${access_key}" ]; then
    printf 'skipped (BACKUP_S3_ACCESS_KEY_ID unset)'
    return 0
  fi
  secret_key=$(read_env_value BACKUP_S3_SECRET_ACCESS_KEY)
  if [ -z "${secret_key}" ]; then
    printf 'skipped (BACKUP_S3_SECRET_ACCESS_KEY unset)'
    return 0
  fi
  endpoint=$(read_env_value BACKUP_S3_ENDPOINT)
  if ! docker image inspect rclone/rclone:1.66 >/dev/null 2>&1; then
    timeout 60 docker pull -q rclone/rclone:1.66 >/dev/null 2>&1 || true
  fi
  rc=0
  if [ -n "${endpoint}" ]; then
    body=$(timeout 6 docker run --rm \
      -e RCLONE_CONFIG_OFFBOX_TYPE=s3 \
      -e RCLONE_CONFIG_OFFBOX_PROVIDER=Other \
      -e RCLONE_CONFIG_OFFBOX_ACCESS_KEY_ID="${access_key}" \
      -e RCLONE_CONFIG_OFFBOX_SECRET_ACCESS_KEY="${secret_key}" \
      -e RCLONE_CONFIG_OFFBOX_ENDPOINT="${endpoint}" \
      rclone/rclone:1.66 lsd "offbox:${bucket}" 2>&1) || rc=$?
  else
    body=$(timeout 6 docker run --rm \
      -e RCLONE_CONFIG_OFFBOX_TYPE=s3 \
      -e RCLONE_CONFIG_OFFBOX_PROVIDER=AWS \
      -e RCLONE_CONFIG_OFFBOX_ACCESS_KEY_ID="${access_key}" \
      -e RCLONE_CONFIG_OFFBOX_SECRET_ACCESS_KEY="${secret_key}" \
      rclone/rclone:1.66 lsd "offbox:${bucket}" 2>&1) || rc=$?
  fi
  if [ "${rc}" -eq 0 ]; then
    printf 'ok'
    return 0
  fi
  reason=$(printf '%s' "${body}" | tr '\n\r' '  ' | cut -c1-200)
  if [ -z "${reason}" ]; then
    reason="rclone lsd offbox:${bucket} did not return 0 within the 6s budget"
  fi
  printf 'failed (%s)' "${reason}"
  return 0
}

cmd_version() {
  printf '%s\n' "${INSTALLER_CONFIG_VERSION}"
}

cmd_help() {
  usage
}

cmd_status() {
  resolve_repo_root
  path=$(state_path)
  if [ ! -f "${path}" ]; then
    printf 'not installed (no %s at %s)\n' "${STATE_FILE_NAME}" "${REPO_ROOT}"
    return 0
  fi
  cat "${path}"
}

cmd_check() {
  resolve_repo_root
  if ! preflight; then
    exit 1
  fi
  echo "deploy.preflight.ok installer_config_version=${INSTALLER_CONFIG_VERSION} repo_root=${REPO_ROOT}"
}

cmd_install() {
  resolve_repo_root
  preflight_err=""
  if ! preflight_err=$(preflight 2>&1 1>/dev/null); then
    if [ -n "${preflight_err}" ]; then
      printf '%s\n' "${preflight_err}" >&2
    fi
    write_failure preflight "${preflight_err}"
    exit 1
  fi

  deployed=$(read_state_version)
  if [ -z "${deployed}" ]; then
    deployed=0
  fi

  run_migrations "${deployed}"

  if ! bring_up_vps_profile; then
    msg="docker compose --profile vps up -d --build returned a non-zero exit"
    echo "deploy.compose.error ${msg}" >&2
    write_failure compose "${msg}"
    exit 1
  fi

  loop=$(probe_loopback_health)
  pub=$(probe_public_tls)

  if [ "${loop}" != "ok" ]; then
    msg="loopback /health probe did not return HTTP 200 within the 30s budget"
    echo "deploy.probe.error ${msg}" >&2
    write_failure probe "${msg}"
    exit 1
  fi

  webhook=$(register_telegram_webhook "${pub}")
  webhook_url=""
  case "${webhook}" in
    registered\ \(*\))
      webhook_url=${webhook#registered \(}
      webhook_url=${webhook_url%\)}
      ;;
  esac

  offbox=$(probe_offbox_backup)

  write_state_success "${loop}" "${pub}" "${webhook}" "${webhook_url}" "${offbox}"

  if [ "${deployed}" -lt "${INSTALLER_CONFIG_VERSION}" ]; then
    echo "deploy.install.ok upgraded v${deployed}->v${INSTALLER_CONFIG_VERSION} loopback_health=${loop} public_tls_probe=\"${pub}\" webhook_registration=\"${webhook}\" offbox_backup_probe=\"${offbox}\""
  else
    echo "deploy.install.ok already_at_v${INSTALLER_CONFIG_VERSION} re-applied loopback_health=${loop} public_tls_probe=\"${pub}\" webhook_registration=\"${webhook}\" offbox_backup_probe=\"${offbox}\""
  fi
}

cmd_unregister_webhook() {
  resolve_repo_root
  if [ ! -f "${REPO_ROOT}/.env" ]; then
    echo "deploy.webhook.error missing .env at ${REPO_ROOT}/.env — fill TELEGRAM_BOT_TOKEN before unregistering" >&2
    exit 1
  fi
  token=$(read_env_value TELEGRAM_BOT_TOKEN)
  if [ -z "${token}" ]; then
    echo "deploy.webhook.error TELEGRAM_BOT_TOKEN unset in .env — cannot call deleteWebhook" >&2
    exit 1
  fi
  body=$(curl -fsS "https://api.telegram.org/bot${token}/deleteWebhook" 2>/dev/null) || body=""
  case "${body}" in
    *'"ok":true'*)
      ;;
    *)
      reason=$(printf '%s' "${body}" | tr -d '\n' | cut -c1-200)
      [ -z "${reason}" ] && reason="deleteWebhook did not return ok:true"
      echo "deploy.webhook.error ${reason}" >&2
      exit 1
      ;;
  esac
  if [ -f "$(state_path)" ]; then
    write_state_unregistered
  fi
  echo "deploy.webhook.unregistered ok"
}

# --- entry point ---------------------------------------------------------

if [ "$#" -eq 0 ]; then
  cmd_install
else
  case "$1" in
    --check)               cmd_check ;;
    --status)              cmd_status ;;
    --version)             cmd_version ;;
    --unregister-webhook)  cmd_unregister_webhook ;;
    -h|--help)             cmd_help ;;
    *)
      echo "deploy.args.error unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
fi
