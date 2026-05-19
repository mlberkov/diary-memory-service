#!/bin/sh
# OP-4.2 — one physical base backup of the reference Postgres cluster (D-054).
#
# Writes a tar+gzip base backup under /archive/base/base-<UTC-ISO8601> and
# records the start WAL segment (consumed by prune.sh -> pg_archivecleanup).
# Holds the shared /archive/.backup.lock for its whole run, so it can never
# overlap a second backup or a concurrent prune. A busy lock is a clean no-op.
set -eu

ARCHIVE=/archive
LOCK="${ARCHIVE}/.backup.lock"
BASE_DIR="${ARCHIVE}/base"

# --- single-run lock (shared with prune.sh) --------------------------------
exec 9>"${LOCK}"
if ! flock -n 9; then
  echo "pg_backup.lock.busy script=backup another run is active; skipping"
  exit 0
fi

PGHOST="${POSTGRES_HOST:-postgres}"
PGUSER="${POSTGRES_USER:-postgres}"
export PGPASSWORD="${POSTGRES_PASSWORD:-postgres}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
dest="${BASE_DIR}/base-${ts}"
mkdir -p "${dest}"

# If the run fails before it completes, remove the partial/empty backup dir:
# a stray dir with no START_WAL marker would otherwise become the "oldest"
# backup and block WAL pruning (prune.sh keys retention on START_WAL). The
# trap is disarmed once the backup is fully written and recorded.
trap 'rm -rf "${dest}"' EXIT

echo "pg_backup.base.start dest=${dest}"

# --format=tar     : compact, restore-friendly, one tar per tablespace
# --wal-method=none: do NOT stream WAL into the backup — PITR replays the
#                    continuously-archived WAL stream instead (D-053)
# --gzip           : compress the tar members
# --checkpoint=fast: immediate checkpoint so the backup starts without waiting
pg_basebackup \
  --host="${PGHOST}" --username="${PGUSER}" \
  --pgdata="${dest}" \
  --format=tar --wal-method=none --gzip --checkpoint=fast \
  --label="op-4.2 base ${ts}"

# Record the start WAL segment — the segment PITR replays FROM and the key
# prune.sh / pg_archivecleanup use to decide which older WAL is prunable.
# backup_label sits at the root of the main base tar.
start_wal="$(tar -xzOf "${dest}/base.tar.gz" backup_label 2>/dev/null \
  | awk '/^START WAL LOCATION/ { gsub(/[()]/, ""); print $6 }')"
if [ -z "${start_wal}" ]; then
  echo "pg_backup.base.error dest=${dest} could not extract START WAL from backup_label"
  exit 1
fi
printf '%s\n' "${start_wal}" > "${dest}/START_WAL"

trap - EXIT
echo "pg_backup.base.ok dest=${dest} start_wal=${start_wal}"
