#!/bin/sh
# OP-4.2 — single long-running backup scheduler for the reference Postgres
# shape (D-054). One scheduler.sh process per pg_backup container.
#
# Once per calendar day, when the local hour (TZ) is inside the configured
# window, it runs backup.sh then prune.sh and records the outcome:
#   - /archive/last_success.json  on a clean backup+prune cycle
#   - /archive/last_failure.json  on a failed cycle (removed on next success)
#
# One-off manual runs must go through `make backup-run` / `make backup-prune`
# (or the equivalent `docker compose run` commands) — never by launching a
# second scheduler.sh, which would create a competing scheduler.
set -u

ARCHIVE=/archive
HERE="$(dirname "$0")"
WINDOW_START="${BACKUP_WINDOW_START:-3}"
WINDOW_END="${BACKUP_WINDOW_END:-5}"
RETENTION_DAYS="${BASE_RETENTION_DAYS:-30}"
LAST_RUN_FILE="${ARCHIVE}/LAST_RUN_DATE"
POLL_SECONDS=600

mkdir -p "${ARCHIVE}/wal" "${ARCHIVE}/base"

# Collapse newlines and escape the few characters that would break a JSON
# string literal. Keeps the marker files valid without a JSON toolchain.
json_escape() {
  printf '%s' "$1" | tr '\n\r' '  ' | sed 's/\\/\\\\/g; s/"/\\"/g'
}

record_success() {
  cat > "${ARCHIVE}/last_success.json" <<EOF
{
  "timestamp": "$1",
  "base_backup": "$2",
  "prune": "$(json_escape "$3")"
}
EOF
  rm -f "${ARCHIVE}/last_failure.json"
}

record_failure() {
  last_line="$(printf '%s' "$3" | tail -n1)"
  cat > "${ARCHIVE}/last_failure.json" <<EOF
{
  "timestamp": "$1",
  "stage": "$2",
  "error": "$(json_escape "${last_line}")"
}
EOF
  echo "pg_backup.cycle.error stage=$2"
}

run_cycle() {
  cycle_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  backup_out="$(sh "${HERE}/backup.sh" 2>&1)"; backup_rc=$?
  echo "${backup_out}"
  if [ "${backup_rc}" -ne 0 ]; then
    record_failure "${cycle_ts}" "backup" "${backup_out}"
    return 1
  fi
  # A busy lock is a clean no-op — not a completed cycle, not a failure.
  if echo "${backup_out}" | grep -q 'pg_backup.lock.busy'; then
    echo "pg_backup.cycle.skip reason=lock-busy"
    return 1
  fi
  base_dir="$(echo "${backup_out}" \
    | sed -n 's/.*pg_backup\.base\.ok dest=\([^ ]*\).*/\1/p')"

  prune_out="$(sh "${HERE}/prune.sh" 2>&1)"; prune_rc=$?
  echo "${prune_out}"
  if [ "${prune_rc}" -ne 0 ]; then
    record_failure "${cycle_ts}" "prune" "${prune_out}"
    return 1
  fi
  prune_summary="$(echo "${prune_out}" \
    | sed -n 's/.*pg_backup\.prune\.ok \(.*\)/\1/p')"

  base_name="$(basename "${base_dir}")"
  record_success "${cycle_ts}" "${base_name}" "${prune_summary}"
  echo "pg_backup.cycle.ok base=${base_name}"
  return 0
}

echo "pg_backup.scheduler.start window=${WINDOW_START}-${WINDOW_END} tz=${TZ:-UTC} retention_days=${RETENTION_DAYS} poll_seconds=${POLL_SECONDS}"

while true; do
  today="$(date +%Y-%m-%d)"
  hour="$(date +%H | sed 's/^0//')"
  [ -z "${hour}" ] && hour=0
  last_run=""
  [ -f "${LAST_RUN_FILE}" ] && last_run="$(cat "${LAST_RUN_FILE}")"

  if [ "${today}" != "${last_run}" ] \
     && [ "${hour}" -ge "${WINDOW_START}" ] \
     && [ "${hour}" -lt "${WINDOW_END}" ]; then
    echo "pg_backup.cycle.begin date=${today} hour=${hour}"
    if run_cycle; then
      printf '%s\n' "${today}" > "${LAST_RUN_FILE}"
    fi
  fi

  sleep "${POLL_SECONDS}"
done
