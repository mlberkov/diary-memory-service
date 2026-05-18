#!/bin/sh
# OP-4.2 — retention pruning for the reference Postgres backup archive (D-054).
#
# Stage A: drop base backups older than BASE_RETENTION_DAYS (default 30).
# Stage B: drop archived WAL no longer needed to recover from the oldest
#          *retained* base backup, via pg_archivecleanup keyed on that
#          backup's recorded START_WAL. Fail-safe: if there is no retained
#          base backup with a START_WAL marker, no WAL is pruned.
#
# Holds the shared /archive/.backup.lock so it can never run while a backup is
# still in progress, or alongside a second prune. A busy lock is a clean no-op.
set -eu

ARCHIVE=/archive
LOCK="${ARCHIVE}/.backup.lock"
BASE_DIR="${ARCHIVE}/base"
WAL_DIR="${ARCHIVE}/wal"
RETENTION_DAYS="${BASE_RETENTION_DAYS:-30}"

# --- single-run lock (shared with backup.sh) -------------------------------
exec 9>"${LOCK}"
if ! flock -n 9; then
  echo "pg_backup.lock.busy script=prune another run is active; skipping"
  exit 0
fi

base_removed=0

# --- Stage A: prune base backups older than the retention window -----------
for d in $(find "${BASE_DIR}" -maxdepth 1 -type d -name 'base-*' \
             -mtime "+${RETENTION_DAYS}" 2>/dev/null | sort); do
  echo "pg_backup.prune.base remove=${d}"
  rm -rf "${d}"
  base_removed=$((base_removed + 1))
done

# --- Stage B: prune WAL older than the oldest *retained* base backup -------
# After Stage A the lexically-smallest surviving base-* dir is the oldest
# retained backup (UTC-ISO8601 names sort chronologically).
oldest="$(find "${BASE_DIR}" -maxdepth 1 -type d -name 'base-*' 2>/dev/null \
            | sort | head -n1)"
wal_summary="no prune"
if [ -n "${oldest}" ] && [ -f "${oldest}/START_WAL" ]; then
  keep_seg="$(cat "${oldest}/START_WAL")"
  before="$(find "${WAL_DIR}" -type f 2>/dev/null | wc -l)"
  echo "pg_backup.prune.wal keep_from=${keep_seg} oldest_base=${oldest}"
  pg_archivecleanup "${WAL_DIR}" "${keep_seg}"
  after="$(find "${WAL_DIR}" -type f 2>/dev/null | wc -l)"
  wal_summary="$((before - after)) WAL segment(s) removed"
else
  echo "pg_backup.prune.wal SKIP no retained base backup with START_WAL; keeping all WAL"
fi

echo "pg_backup.prune.ok base_removed=${base_removed}; wal=${wal_summary}"
