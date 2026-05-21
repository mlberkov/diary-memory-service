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
# Single canonical operator command: ./scripts/installer/deploy.sh
# See docs/RUNBOOK.md "Installer / upgrade script (DEPLOY-1.4 / D-063)".

set -eu

INSTALLER_CONFIG_VERSION=1

STATE_FILE_NAME=".installer-state.json"
FAILURE_FILE_NAME=".installer-state.last_failure.json"

# Required keys for the vps-profile public-TLS contour (DEPLOY-1.3 / D-062).
REQUIRED_ENV_KEYS="POSTGRES_PASSWORD PUBLIC_HOSTNAME ACME_EMAIL"

# Set later by resolve_repo_root.
REPO_ROOT=""

usage() {
  cat <<'USAGE'
usage: deploy.sh [--check | --status | --version | --help]

  (none)      Install or upgrade depending on .installer-state.json state.
              The canonical operator command. Non-interactive: reads .env;
              runs `docker compose --profile vps up -d --build`; probes
              loopback /health (mandatory) and public-TLS /health
              (best-effort); writes .installer-state.json on success.
  --check     Preflight only. Reads inputs, writes nothing. Exit 0 if all
              preconditions are satisfied; non-zero with diagnostics otherwise.
  --status    Print the current .installer-state.json (or "not installed"
              if absent). Exits 0.
  --version   Print INSTALLER_CONFIG_VERSION. Exits 0.
  --help      Print this usage.

Documented in docs/RUNBOOK.md "Installer / upgrade script (DEPLOY-1.4 / D-063)".
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

# write_state_success <loopback> <public_tls>
write_state_success() {
  loopback="$1"
  public_tls="$2"
  ts=$(now_utc_iso)
  cat > "$(state_path)" <<EOF
{
  "installer_config_version": ${INSTALLER_CONFIG_VERSION},
  "selected_defaults": {
    "reverse_proxy": "caddy",
    "installer_impl": "bash",
    "backup_tool": null
  },
  "last_install_timestamp": "${ts}",
  "last_outcome": "success",
  "loopback_health": "${loopback}",
  "public_tls_probe": "${public_tls}"
}
EOF
  rm -f "$(failure_path)"
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
  # When DEPLOY-1.x packets add migrate_v1_to_v2 etc., extend this chain.
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

  write_state_success "${loop}" "${pub}"

  if [ "${deployed}" -lt "${INSTALLER_CONFIG_VERSION}" ]; then
    echo "deploy.install.ok upgraded v${deployed}->v${INSTALLER_CONFIG_VERSION} loopback_health=${loop} public_tls_probe=\"${pub}\""
  else
    echo "deploy.install.ok already_at_v${INSTALLER_CONFIG_VERSION} re-applied loopback_health=${loop} public_tls_probe=\"${pub}\""
  fi
}

# --- entry point ---------------------------------------------------------

if [ "$#" -eq 0 ]; then
  cmd_install
else
  case "$1" in
    --check)   cmd_check ;;
    --status)  cmd_status ;;
    --version) cmd_version ;;
    -h|--help) cmd_help ;;
    *)
      echo "deploy.args.error unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
fi
