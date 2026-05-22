#!/bin/sh
# DEPLOY-1.6 / D-065 — best-effort, additive off-box backup uploader for the
# reference Postgres shape. One long-running uploader.sh process per
# pg_offbox_uploader container, gated by the same `backup` Compose profile
# as the pg_backup sidecar (`docker compose --profile backup up -d`).
#
# Trigger: polls /archive/last_success.json (the OP-4.2 durable success
# marker written by scripts/pg_backup/scheduler.sh after a clean
# backup+prune cycle). When a previously-unseen cycle is observed, runs
#   rclone sync /archive/base  -> ${REMOTE}/${PREFIX}/base
#   rclone sync /archive/wal   -> ${REMOTE}/${PREFIX}/wal
# and records the outcome in /archive/last_offbox.json.
#
# Narrow write scope (additive observability — never regresses OP-4):
#   - /archive/last_success.json is READ ONLY by this script.
#   - /archive/base and /archive/wal are READ ONLY by this script.
#   - The ONLY file this script writes under /archive is
#     /archive/last_offbox.json. pg_backup.cycle.ok semantics and the
#     OP-4.2 durable signal are never affected by an uploader failure.
#
# Credentials are passed via env vars only and are never echoed in log
# lines on failure — categorized reason classes (auth_failed / network /
# remote_error / temporary / fatal) replace raw rclone stderr.

set -u

ARCHIVE=/archive
POLL_SECONDS=600
REMOTE_NAME=offbox

# Collapse newlines and escape JSON-breaking characters for a string
# literal. Keeps the cursor file valid without a JSON toolchain.
json_escape() {
  printf '%s' "$1" | tr '\n\r' '  ' | sed 's/\\/\\\\/g; s/"/\\"/g'
}

# Read a top-level scalar JSON string field from a file. Empty when
# absent. Matches the pg_backup / installer shape — sufficient for the
# installer-and-pg-backup-owned files this script reads.
json_field() {
  key="$1"; path="$2"
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

# write_cursor <timestamp> <base_backup> <status> <error_or_empty>
write_cursor() {
  ts="$1"; base="$2"; status="$3"; err="$4"
  if [ -z "${err}" ]; then
    err_field="null"
  else
    err_field="\"$(json_escape "${err}")\""
  fi
  cat > "${ARCHIVE}/last_offbox.json" <<EOF
{
  "timestamp": "${ts}",
  "base_backup": "${base}",
  "status": "${status}",
  "error": ${err_field}
}
EOF
}

# Map a non-zero rclone exit code + stderr blob to a single short reason
# class. Never echoes credentials. Per the rclone docs the codes mean:
#   1 syntax/usage   2 generic error            3 dir not found
#   4 file not found 5 temporary (retryable)    6 less-serious
#   7 fatal          8 transfer exceeded        9 ok but no files moved
# We coalesce to: auth_failed / network / remote_error / temporary / fatal.
categorize_error() {
  rc="$1"; body="$2"
  case "${rc}" in
    5)
      echo "temporary"
      return 0
      ;;
    7)
      echo "fatal"
      return 0
      ;;
  esac
  if echo "${body}" | grep -qiE 'forbidden|access ?denied|signature|invalid ?access|unauthor|403|401'; then
    echo "auth_failed"
  elif echo "${body}" | grep -qiE 'connection|timeout|dial|refused|no such host|network'; then
    echo "network"
  else
    echo "remote_error"
  fi
}

# Sync one local directory to the remote. Returns non-zero on failure
# with the categorized reason class in $REASON_CLASS.
sync_dir() {
  local_dir="$1"; remote_sub="$2"
  rc=0
  body=$(rclone sync "${local_dir}" \
    "${REMOTE_NAME}:${BACKUP_S3_BUCKET}/${PREFIX}/${remote_sub}" 2>&1) || rc=$?
  if [ "${rc}" -eq 0 ]; then
    REASON_CLASS=""
    return 0
  fi
  REASON_CLASS="$(categorize_error "${rc}" "${body}")"
  REASON_RC="${rc}"
  return 1
}

# Configure the rclone remote via env (no rclone.conf file). The remote
# name is fixed to `offbox` so the sync commands read clean.
export RCLONE_CONFIG_OFFBOX_TYPE=s3
export RCLONE_CONFIG_OFFBOX_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY_ID:-}"
export RCLONE_CONFIG_OFFBOX_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_ACCESS_KEY:-}"
if [ -n "${BACKUP_S3_ENDPOINT:-}" ]; then
  export RCLONE_CONFIG_OFFBOX_PROVIDER=Other
  export RCLONE_CONFIG_OFFBOX_ENDPOINT="${BACKUP_S3_ENDPOINT}"
else
  export RCLONE_CONFIG_OFFBOX_PROVIDER=AWS
fi
PREFIX="${BACKUP_S3_PATH_PREFIX:-archive}"

echo "pg_backup.offbox.start bucket=${BACKUP_S3_BUCKET:-(unset)} endpoint=${BACKUP_S3_ENDPOINT:-(default-aws)} prefix=${PREFIX} poll_seconds=${POLL_SECONDS}"

# In-memory cursor of the last cycle we have successfully uploaded; the
# /archive/last_offbox.json cursor is the persistent operator-facing
# surface but is not the trigger source.
LAST_UPLOADED_TS=""

# Throttle the skipped-config log so a misconfigured uploader does not
# fill the journal — log once per state change.
LAST_SKIP_REASON=""

while true; do
  if [ -z "${BACKUP_S3_BUCKET:-}" ]; then
    if [ "${LAST_SKIP_REASON}" != "bucket" ]; then
      echo "pg_backup.offbox.skipped reason=BACKUP_S3_BUCKET unset"
      LAST_SKIP_REASON="bucket"
    fi
    sleep "${POLL_SECONDS}"
    continue
  fi
  if [ -z "${BACKUP_S3_ACCESS_KEY_ID:-}" ]; then
    if [ "${LAST_SKIP_REASON}" != "access_key" ]; then
      echo "pg_backup.offbox.skipped reason=BACKUP_S3_ACCESS_KEY_ID unset"
      LAST_SKIP_REASON="access_key"
    fi
    sleep "${POLL_SECONDS}"
    continue
  fi
  if [ -z "${BACKUP_S3_SECRET_ACCESS_KEY:-}" ]; then
    if [ "${LAST_SKIP_REASON}" != "secret_key" ]; then
      echo "pg_backup.offbox.skipped reason=BACKUP_S3_SECRET_ACCESS_KEY unset"
      LAST_SKIP_REASON="secret_key"
    fi
    sleep "${POLL_SECONDS}"
    continue
  fi
  LAST_SKIP_REASON=""

  if [ ! -f "${ARCHIVE}/last_success.json" ]; then
    sleep "${POLL_SECONDS}"
    continue
  fi
  cycle_ts="$(json_field timestamp "${ARCHIVE}/last_success.json")"
  cycle_base="$(json_field base_backup "${ARCHIVE}/last_success.json")"
  if [ -z "${cycle_ts}" ]; then
    sleep "${POLL_SECONDS}"
    continue
  fi
  if [ "${cycle_ts}" = "${LAST_UPLOADED_TS}" ]; then
    sleep "${POLL_SECONDS}"
    continue
  fi

  echo "pg_backup.offbox.begin base=${cycle_base} ts=${cycle_ts}"
  if sync_dir "${ARCHIVE}/base" base; then
    if sync_dir "${ARCHIVE}/wal" wal; then
      echo "pg_backup.offbox.ok base=${cycle_base}"
      write_cursor "${cycle_ts}" "${cycle_base}" "ok" ""
      LAST_UPLOADED_TS="${cycle_ts}"
    else
      echo "pg_backup.offbox.error stage=wal reason=${REASON_CLASS} rc=${REASON_RC}"
      write_cursor "${cycle_ts}" "${cycle_base}" "error" "stage=wal reason=${REASON_CLASS} rc=${REASON_RC}"
    fi
  else
    echo "pg_backup.offbox.error stage=base reason=${REASON_CLASS} rc=${REASON_RC}"
    write_cursor "${cycle_ts}" "${cycle_base}" "error" "stage=base reason=${REASON_CLASS} rc=${REASON_RC}"
  fi

  sleep "${POLL_SECONDS}"
done
