#!/bin/sh
# OP-4.3 — operator-grade restore for the reference Postgres shape (D-055).
#
# Prepares a recovered Postgres 16 data directory from an OP-4.2 base backup
# (/archive/base/base-<UTC-ISO8601>/base.tar.gz) plus the continuously
# archived WAL stream (/archive/wal). It supports two recovery targets:
#   --target=latest             replay every archived WAL segment;
#   --target-timestamp=ISO8601  point-in-time recovery to that instant.
#
# It writes the recovery configuration and the recovery.signal file; the
# recovered cluster is then RUN by bringing the `pg_restore` Compose service
# up on the prepared volume (this script does not start Postgres itself).
#
# Safety contour:
#   - it operates only on the dedicated, throwaway `memory_rag_pg_restore_data`
#     scratch volume mounted at --data-dir — never the live data directory;
#   - it refuses to run against an apparently-live cluster (a postmaster.pid
#     in the destination);
#   - a real restore is destructive and requires explicit --yes;
#   - --dry-run validates the backup + WAL and prints the plan, writing
#     nothing.
#
# This script is coupled to the OP-4.2 backup format and /archive layout
# (base-<ts>/{base.tar.gz,backup_manifest,START_WAL}; flat /archive/wal). If
# either changes in a later packet, this script must change in that packet.
set -eu

ARCHIVE=/archive
WAL_DIR="${ARCHIVE}/wal"
LOG_DIR="${ARCHIVE}/restore_logs"

# --- defaults / arguments (CLI flags, with RESTORE_* env fallbacks) --------
BACKUP_DIR="${RESTORE_BACKUP_DIR:-}"
TARGET="${RESTORE_TARGET:-}"
TARGET_TS="${RESTORE_TARGET_TIMESTAMP:-}"
DATA_DIR="${RESTORE_DATA_DIR:-/var/lib/postgresql/data}"
DRY_RUN=0
ASSUME_YES=0

usage() {
  cat <<'USAGE'
usage: restore.sh --backup-dir=DIR (--target=latest | --target-timestamp=ISO8601)
                  [--data-dir=DIR] [--dry-run] [--yes]
USAGE
}

fail() { echo "pg_restore.$1" >&2; exit "${2:-1}"; }

for arg in "$@"; do
  case "${arg}" in
    --backup-dir=*)       BACKUP_DIR="${arg#*=}" ;;
    --target=*)           TARGET="${arg#*=}" ;;
    --target-timestamp=*) TARGET_TS="${arg#*=}" ;;
    --data-dir=*)         DATA_DIR="${arg#*=}" ;;
    --dry-run)            DRY_RUN=1 ;;
    --yes)                ASSUME_YES=1 ;;
    -h|--help)            usage; exit 0 ;;
    *) echo "pg_restore.args.error unknown argument: ${arg}" >&2; usage >&2; exit 2 ;;
  esac
done

# --- validate the arguments ------------------------------------------------
[ -n "${BACKUP_DIR}" ] || fail "args.error --backup-dir is required" 2

if [ -n "${TARGET_TS}" ] && [ "${TARGET}" = "latest" ]; then
  fail "args.error pass only one of --target=latest / --target-timestamp" 2
fi
if [ -z "${TARGET_TS}" ] && [ "${TARGET}" != "latest" ]; then
  fail "args.error pass --target=latest or --target-timestamp=ISO8601" 2
fi
if [ -n "${TARGET}" ] && [ "${TARGET}" != "latest" ]; then
  fail "args.error --target accepts only 'latest'" 2
fi

if [ -n "${TARGET_TS}" ]; then
  MODE=pitr
  TARGET_DESC="point-in-time ${TARGET_TS}"
else
  MODE=latest
  TARGET_DESC="latest (replay all archived WAL)"
fi

# --- validate the backup + WAL --------------------------------------------
BASE_TAR="${BACKUP_DIR}/base.tar.gz"
[ -d "${BACKUP_DIR}" ]                   || fail "validate.error backup dir not found: ${BACKUP_DIR}"
[ -f "${BASE_TAR}" ]                     || fail "validate.error base.tar.gz not found in ${BACKUP_DIR}"
[ -f "${BACKUP_DIR}/backup_manifest" ]   || fail "validate.error backup_manifest missing in ${BACKUP_DIR}"
[ -f "${BACKUP_DIR}/START_WAL" ]         || fail "validate.error START_WAL marker missing in ${BACKUP_DIR}"
START_WAL="$(cat "${BACKUP_DIR}/START_WAL")"
[ -d "${WAL_DIR}" ]                      || fail "validate.error WAL archive dir not found: ${WAL_DIR}"
[ -f "${WAL_DIR}/${START_WAL}" ]         || fail "validate.error start WAL segment ${START_WAL} missing from ${WAL_DIR}"
WAL_COUNT="$(find "${WAL_DIR}" -maxdepth 1 -type f \
               -name '????????????????????????' 2>/dev/null | wc -l | tr -d ' ')"
echo "pg_restore.validate.ok backup=${BACKUP_DIR} start_wal=${START_WAL} wal_segments=${WAL_COUNT}"

# --- safety check on the destination data directory -----------------------
if [ -e "${DATA_DIR}/postmaster.pid" ]; then
  fail "safety.error ${DATA_DIR} holds postmaster.pid — a cluster may be running there; run 'docker compose --profile restore down' first" 3
fi
EXISTING_CLUSTER=0
if [ -f "${DATA_DIR}/PG_VERSION" ]; then
  EXISTING_CLUSTER=1
fi

# --- print the plan before doing anything ---------------------------------
echo "pg_restore.plan source_backup=${BACKUP_DIR}"
echo "pg_restore.plan recovery_target=${TARGET_DESC}"
echo "pg_restore.plan destination=${DATA_DIR}"
if [ "${EXISTING_CLUSTER}" -eq 1 ]; then
  echo "pg_restore.plan note destination already contains a cluster — a real run replaces it"
fi

# --- dry-run: validation + plan only, no changes --------------------------
if [ "${DRY_RUN}" -eq 1 ]; then
  if [ "${MODE}" = pitr ]; then
    echo "pg_restore.dryrun note the PITR end segment cannot be confirmed before replay — ensure archived WAL covers ${TARGET_TS}"
  fi
  echo "pg_restore.dryrun.ok no changes made"
  exit 0
fi

# --- explicit confirmation for a real (destructive) restore ---------------
if [ "${ASSUME_YES}" -ne 1 ]; then
  fail "confirm.error refusing to restore without --yes — a real run replaces ${DATA_DIR}" 3
fi
if [ "${EXISTING_CLUSTER}" -eq 1 ]; then
  echo "pg_restore.confirm replacing the existing cluster at ${DATA_DIR} (--yes given)"
fi

# --- prepare the recovered data directory ---------------------------------
mkdir -p "${LOG_DIR}"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_LOG="${LOG_DIR}/restore-${ts}.log"
START_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
START_EPOCH="$(date -u +%s)"

log() { echo "$1" | tee -a "${RUN_LOG}"; }

log "pg_restore.run.start ts=${ts} backup=${BACKUP_DIR} target=${TARGET_DESC} dest=${DATA_DIR}"

# 1. empty the scratch data directory
log "pg_restore.run.clear ${DATA_DIR}"
find "${DATA_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +

# 2. extract the physical base backup
log "pg_restore.run.extract ${BASE_TAR}"
tar -xzf "${BASE_TAR}" -C "${DATA_DIR}"

# 3. recovery configuration — restore_command reads the archived WAL stream;
#    a timestamp target promotes once that instant is reached.
log "pg_restore.run.config mode=${MODE}"
{
  echo ""
  echo "# OP-4.3 restore.sh — recovery configuration (${ts})"
  echo "restore_command = 'cp ${WAL_DIR}/%f %p'"
  if [ "${MODE}" = pitr ]; then
    echo "recovery_target_time = '${TARGET_TS}'"
    echo "recovery_target_action = 'promote'"
  fi
} >> "${DATA_DIR}/postgresql.auto.conf"

# 4. recovery.signal triggers archive recovery on the next start (PG12+)
touch "${DATA_DIR}/recovery.signal"

# 5. ownership + permissions for the postgres OS user (UID 999)
chown -R 999:999 "${DATA_DIR}"
chmod 700 "${DATA_DIR}"

END_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
END_EPOCH="$(date -u +%s)"
PREP_SECONDS=$((END_EPOCH - START_EPOCH))

log "pg_restore.run.ok prep_seconds=${PREP_SECONDS}"
log "pg_restore.run.next start the recovered cluster: docker compose --profile restore up -d pg_restore"

# concise result marker — primary evidence for the OP-4.3 drill and future runs
cat > "${LOG_DIR}/last_restore.json" <<EOF
{
  "status": "prepared",
  "ts": "${ts}",
  "backup_dir": "${BACKUP_DIR}",
  "recovery_target": "${TARGET_DESC}",
  "destination": "${DATA_DIR}",
  "prep_started_utc": "${START_ISO}",
  "prep_finished_utc": "${END_ISO}",
  "prep_seconds": ${PREP_SECONDS},
  "run_log": "${RUN_LOG}"
}
EOF
echo "pg_restore.run.marker ${LOG_DIR}/last_restore.json"
