#!/bin/sh
# OP-4.2 — allow physical replication connections so the pg_backup sidecar can
# run pg_basebackup over the Compose network (D-054).
#
# Runs once, during the initial cluster bootstrap (mounted into
# /docker-entrypoint-initdb.d). The default pg_hba.conf from the postgres image
# permits replication only over local connections; the nightly base backup
# connects from a separate container and needs an explicit host rule. Password
# auth (scram-sha-256) matches the image's appended `host all all all` rule;
# the sidecar authenticates with PGPASSWORD.
#
# Because this is an initdb-time hook, an already-initialized data volume does
# not pick it up — enabling OP-4.2 on a pre-existing local volume needs a
# `docker compose down -v` reset (same precedent as A-34).
set -eu
printf 'host replication all all scram-sha-256\n' >> "${PGDATA}/pg_hba.conf"
echo "op-4.2: appended 'host replication' rule to pg_hba.conf"
