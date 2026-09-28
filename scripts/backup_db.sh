#!/bin/sh
# Manual database backup.
# Usage: ./scripts/backup_db.sh [compose-file]     (default: docker-compose.prod.yml)
# Output: ./backups/<db>_<UTC timestamp>_manual.dump  (pg_dump custom format)
set -eu

COMPOSE_FILE="${1:-docker-compose.prod.yml}"
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"

docker compose -f "$COMPOSE_FILE" exec -T db sh -c \
  'pg_dump --format=custom --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > "backups/leadfinder_${stamp}_manual.dump.partial"
mv "backups/leadfinder_${stamp}_manual.dump.partial" "backups/leadfinder_${stamp}_manual.dump"
echo "Backup written to backups/leadfinder_${stamp}_manual.dump"
