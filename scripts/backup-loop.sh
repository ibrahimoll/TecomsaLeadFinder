#!/bin/sh
# Scheduled PostgreSQL backups (runs inside the `backup` service of docker-compose.prod.yml).
# Writes compressed custom-format dumps to /backups and prunes old ones.
set -eu

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target="/backups/${PGDATABASE}_${stamp}.dump"
  if pg_dump --format=custom --no-owner --file="${target}.partial"; then
    mv "${target}.partial" "${target}"
    echo "[backup] ${stamp} wrote ${target} ($(du -h "${target}" | cut -f1))"
  else
    rm -f "${target}.partial"
    echo "[backup] ${stamp} FAILED" >&2
  fi
  find /backups -name "${PGDATABASE}_*.dump" -type f -mtime "+${RETENTION_DAYS}" -print -delete || true
  sleep "${INTERVAL}"
done
