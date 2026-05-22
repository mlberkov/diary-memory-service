#!/usr/bin/env bash
# DEPLOY-1.7-preflight / D-066 — local-only upgrade-drill harness across real
# prior commits. Operates within DEPLOY-1 invariants — A-22 updated by D-060.
#
# Exercises the D-063 configuration-versioning seam (INSTALLER_CONFIG_VERSION
# + the migrate_v<old>_to_v<new> chain) by running the unchanged
# scripts/installer/deploy.sh against real prior packet commits in a
# sandboxed git worktree under `mktemp -d`. The main repo working tree is
# never modified by the drill (the harness script itself is added in this
# packet at HEAD and does not exist at the prior commits; an in-place
# checkout would erase it mid-run).
#
# Single canonical invocation: ./scripts/installer/drill_upgrade_local.sh
# See docs/RUNBOOK.md "Local-only upgrade-drill preflight
# (DEPLOY-1.7-preflight / D-066)".

set -eu

LEG1_COMMIT=7cb96fa
LEG2_COMMIT=e435e1a
LEG3_COMMIT=0aef179
PROJECT_NAME=deploy1-preflight-drill

MAIN_REPO=""
TMP=""
WORKTREE=""
DRILL_OK=0

resolve_main_repo() {
  script_dir=$(cd -- "$(dirname -- "$0")" && pwd -P)
  candidate="${script_dir}"
  while [ "${candidate}" != "/" ]; do
    if [ -f "${candidate}/Dockerfile" ] \
        && [ -f "${candidate}/docker-compose.yml" ] \
        && [ -f "${candidate}/pyproject.toml" ]; then
      MAIN_REPO="${candidate}"
      return 0
    fi
    candidate=$(dirname -- "${candidate}")
  done
  echo "preflight.error could not locate main repo root (Dockerfile + docker-compose.yml + pyproject.toml co-located) from $0" >&2
  exit 1
}

harness_preflight() {
  for tool in git docker mktemp python3 grep; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
      echo "preflight.error required tool not on PATH: ${tool}" >&2
      exit 1
    fi
  done
  if ! docker compose version >/dev/null 2>&1; then
    echo "preflight.error docker compose v2 plugin not available" >&2
    exit 1
  fi
  if ! git -C "${MAIN_REPO}" rev-parse --git-dir >/dev/null 2>&1; then
    echo "preflight.error main repo is not a git checkout: ${MAIN_REPO}" >&2
    exit 1
  fi
  for sha in "${LEG1_COMMIT}" "${LEG2_COMMIT}" "${LEG3_COMMIT}"; do
    if ! git -C "${MAIN_REPO}" cat-file -e "${sha}^{commit}" 2>/dev/null; then
      echo "preflight.error prior commit not reachable in this checkout: ${sha}" >&2
      exit 1
    fi
  done
}

cleanup() {
  if [ "${DRILL_OK}" = 1 ]; then
    if [ -n "${WORKTREE}" ] && [ -d "${WORKTREE}" ]; then
      git -C "${MAIN_REPO}" worktree remove --force "${WORKTREE}" >/dev/null 2>&1 || true
    fi
    if [ -n "${TMP}" ] && [ -d "${TMP}" ]; then
      rm -rf "${TMP}" >/dev/null 2>&1 || true
    fi
  else
    if [ -n "${WORKTREE}" ] && [ -d "${WORKTREE}" ]; then
      echo "preflight.cleanup worktree preserved at ${WORKTREE} (run 'git -C ${MAIN_REPO} worktree remove --force ${WORKTREE}' to remove)" >&2
    fi
  fi
}

write_env() {
  cat > "${WORKTREE}/.env" <<EOF
POSTGRES_PASSWORD=postgres-secret
PUBLIC_HOSTNAME=deploy1-preflight.invalid
ACME_EMAIL=preflight@example.invalid
TELEGRAM_BOT_TOKEN=placeholder-bot-token
TELEGRAM_WEBHOOK_SECRET=placeholder-secret
EOF
}

run_leg() {
  n="$1"
  commit="$2"
  label="$3"
  expected="$4"

  echo "preflight.leg.start n=${n} commit=${commit} label=${label} expected_version=${expected}"

  git -C "${WORKTREE}" checkout -q --detach "${commit}"
  write_env

  log="${LEG_LOGS_DIR}/leg-${n}.log"
  start=$(date +%s)
  set +e
  ( cd "${WORKTREE}" && ./scripts/installer/deploy.sh ) > "${log}" 2>&1
  exit_code=$?
  set -e
  elapsed=$(( $(date +%s) - start ))

  state_file="${WORKTREE}/.installer-state.json"
  failure_file="${WORKTREE}/.installer-state.last_failure.json"

  if [ -f "${state_file}" ]; then
    cp "${state_file}" "${EVIDENCE_DIR}/leg-${n}-state.json"
  fi
  if [ -f "${failure_file}" ]; then
    cp "${failure_file}" "${EVIDENCE_DIR}/leg-${n}-last-failure.json"
  fi

  install_ok_line=$(grep -E '^deploy\.install\.ok' "${log}" | tail -n 1 || true)
  printf '%s' "${install_ok_line}" > "${EVIDENCE_DIR}/leg-${n}-install-ok.txt"

  cat > "${EVIDENCE_DIR}/leg-${n}-meta.json" <<EOF
{
  "leg_number": ${n},
  "commit_sha": "${commit}",
  "packet_label": "${label}",
  "expected_installer_config_version": ${expected},
  "exit_code": ${exit_code},
  "elapsed_seconds": ${elapsed}
}
EOF

  echo "preflight.leg.done n=${n} exit_code=${exit_code} elapsed=${elapsed}s"
}

build_evidence_artifact() {
  out_dir="${MAIN_REPO}/docs/deploy1-drill"
  mkdir -p "${out_dir}"
  drill_date=$(date -u +"%Y%m%d")
  out_file="${out_dir}/deploy1-upgrade-drill-${drill_date}-evidence.json"

  export EVIDENCE_DIR_OUT="${EVIDENCE_DIR}"
  export OUT_FILE="${out_file}"
  export WORKTREE_OUT="${WORKTREE}"
  export PROJECT_NAME_OUT="${PROJECT_NAME}"
  export DRILL_DATE_OUT="${drill_date}"

  python3 - <<'PYEOF'
import json
import os

evidence_dir = os.environ["EVIDENCE_DIR_OUT"]
out_file = os.environ["OUT_FILE"]
worktree = os.environ["WORKTREE_OUT"]
project_name = os.environ["PROJECT_NAME_OUT"]
drill_date = os.environ["DRILL_DATE_OUT"]


def maybe_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None


def maybe_text(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        s = f.read().rstrip("\n")
    return s if s else None


legs = []
for n in (1, 2, 3):
    meta = maybe_json(f"{evidence_dir}/leg-{n}-meta.json") or {}
    state = maybe_json(f"{evidence_dir}/leg-{n}-state.json")
    last_failure = maybe_json(f"{evidence_dir}/leg-{n}-last-failure.json")
    install_ok_line = maybe_text(f"{evidence_dir}/leg-{n}-install-ok.txt")

    state_dict = state if isinstance(state, dict) else {}
    selected_defaults = state_dict.get("selected_defaults") or {}
    observed_probes = {
        "public_tls_probe": state_dict.get("public_tls_probe") if state_dict else None,
        "webhook_registration": state_dict.get("webhook_registration") if state_dict else None,
        "offbox_backup_probe": state_dict.get("offbox_backup_probe") if state_dict else None,
        "selected_defaults.backup_tool": selected_defaults.get("backup_tool") if state_dict else None,
    }

    leg = {
        "leg_number": meta.get("leg_number", n),
        "commit_sha": meta.get("commit_sha"),
        "packet_label": meta.get("packet_label"),
        "expected_installer_config_version": meta.get("expected_installer_config_version"),
        "exit_code": meta.get("exit_code"),
        "elapsed_seconds": meta.get("elapsed_seconds"),
        "deploy_install_ok_line": install_ok_line,
        "state_file_after": state,
        "last_failure_after": last_failure,
        "observed_probes": observed_probes,
    }
    legs.append(leg)


def _chain_advanced(legs):
    for leg in legs:
        state = leg.get("state_file_after")
        if not isinstance(state, dict):
            return False
        if state.get("installer_config_version") != leg["expected_installer_config_version"]:
            return False
    return True


chain_advanced = _chain_advanced(legs)
exit_codes = [leg["exit_code"] for leg in legs]
all_exited_zero = all(rc == 0 for rc in exit_codes)
any_exited_zero = any(rc == 0 for rc in exit_codes)

if all_exited_zero and chain_advanced:
    verdict = "preflight ok"
elif any_exited_zero:
    verdict = "preflight partial"
else:
    verdict = "preflight failed"


def per_leg_probe(legs, key):
    return [
        {
            "leg": leg["leg_number"],
            "verbatim": leg["observed_probes"].get(key),
            "classification": "operator_dependent",
        }
        for leg in legs
    ]


evidence = {
    "drill": (
        "DEPLOY-1.7-preflight — local-only upgrade-drill harness "
        "across real prior commits (D-066)"
    ),
    "metadata": {
        "drill_run_date": drill_date,
        "environment": "local docker-compose dev host (git worktree under mktemp -d)",
        "worktree_path": worktree,
        "compose_project_name": project_name,
        "notes": (
            "Local preflight evidence — DEPLOY-1.7 closure remains blocked on "
            "real-VPS / public-DNS / Telegram / real-S3 operator infrastructure. "
            "Procedure follows feedback_real_prior_version_evidence: real "
            "prior-version installs via git checkout, not hand-edited state "
            "files. The harness is inspection, not a closure gate "
            "(feedback_harness_is_inspection_not_gate). Probe verdicts are "
            "captured verbatim in observed_probes and classified as "
            "operator_dependent; the only asserted properties are per-leg "
            "exit_code == 0 and state_file_after.installer_config_version "
            "matching the expected integer."
        ),
    },
    "legs": legs,
    "locally_confirmed_signals": {
        "installer_config_version_chain_advanced": chain_advanced,
        "state_file_shape_transitions": (
            "Per-leg state_file_after snapshots are recorded verbatim; observe "
            "the appearance of the webhook_registration block at leg 2 and "
            "the appearance of the offbox_backup_probe field plus the flip of "
            "selected_defaults.backup_tool to \"rclone\" at leg 3 directly in "
            "the captured JSON."
        ),
        "migration_helpers_fired_in_order": chain_advanced,
    },
    "locally_skipped_signals": {
        "public_tls_probe_per_leg": per_leg_probe(legs, "public_tls_probe"),
        "webhook_registration_per_leg": per_leg_probe(legs, "webhook_registration"),
        "offbox_backup_probe_per_leg": per_leg_probe(legs, "offbox_backup_probe"),
    },
    "out_of_scope_for_closure": [
        "Clean-VPS public DNS + ACME-issued cert path (DEPLOY-1.7).",
        "Real Telegram setWebhook → FastAPI receiver round-trip (DEPLOY-1.7).",
        "Real S3-compatible bucket reachability + rclone sync of /archive/base + /archive/wal (DEPLOY-1.7).",
        "v2 → v3 cross-version migration end-to-end against a real previously-installed v2 VPS (DEPLOY-1.7, per D-065 §\"Real-VPS operator smoke\").",
    ],
    "summary": {
        "seam_exercised_locally": chain_advanced,
        "closes_deploy_1_7": False,
        "deploy_1_7_status": "still open",
        "deploy_1_status": "still open",
        "verdict": verdict,
    },
}

with open(out_file, "w") as f:
    json.dump(evidence, f, indent=2)
    f.write("\n")
print(f"preflight.evidence wrote {out_file}")
PYEOF
}

main() {
  resolve_main_repo
  harness_preflight

  echo "preflight.start main_repo=${MAIN_REPO}"

  TMP=$(mktemp -d -t deploy1-preflight-drill-XXXXXX)
  WORKTREE="${TMP}/repo"

  trap cleanup EXIT

  echo "preflight.worktree path=${WORKTREE}"
  git -C "${MAIN_REPO}" worktree add --detach "${WORKTREE}" HEAD >/dev/null

  export COMPOSE_PROJECT_NAME="${PROJECT_NAME}"

  EVIDENCE_DIR="${WORKTREE}/.preflight-drill-evidence"
  LEG_LOGS_DIR="${WORKTREE}/.preflight-drill-logs"
  mkdir -p "${EVIDENCE_DIR}" "${LEG_LOGS_DIR}"

  run_leg 1 "${LEG1_COMMIT}" "DEPLOY-1.4" 1
  run_leg 2 "${LEG2_COMMIT}" "DEPLOY-1.5" 2
  run_leg 3 "${LEG3_COMMIT}" "DEPLOY-1.6" 3

  ( cd "${WORKTREE}" && docker compose --profile vps down >/dev/null 2>&1 ) || true

  build_evidence_artifact

  # Inspect leg outcomes to decide final stdout label
  any_nonzero=0
  any_zero=0
  for n in 1 2 3; do
    meta="${EVIDENCE_DIR}/leg-${n}-meta.json"
    if [ -f "${meta}" ]; then
      rc=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('exit_code'))" "${meta}")
      if [ "${rc}" = "0" ]; then
        any_zero=1
      else
        any_nonzero=1
      fi
    else
      any_nonzero=1
    fi
  done

  if [ "${any_nonzero}" = "0" ]; then
    echo "deploy1.preflight.ok seam_exercised_locally=true closes_deploy_1_7=false"
    DRILL_OK=1
  elif [ "${any_zero}" = "1" ]; then
    echo "deploy1.preflight.partial seam_exercised_locally=false closes_deploy_1_7=false"
    DRILL_OK=0
  else
    echo "deploy1.preflight.failed seam_exercised_locally=false closes_deploy_1_7=false"
    DRILL_OK=0
  fi
}

main "$@"
