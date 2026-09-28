#!/bin/sh
# Restore a pg_dump custom-format backup INTO THE RUNNING DATABASE, replacing its contents.
# Usage: ./scripts/restore_db.sh backups/<file>.dump [compose-file]
#
# Stop the backend first so no writes happen during the restore:
#   docker compose -f docker-compose.prod.yml stop backend frontend
set -eu

DUMP="${1:?Usage: restore_db.sh <dump-file> [compose-file]}"
COMPOSE_FILE="${2:-docker-compose.prod.yml}"
[ -f "$DUMP" ] || { echo "No such file: $DUMP" >&2; exit 1; }

printf 'This will REPLACE all data in the LeadFinder database with %s. Type "restore" to continue: ' "$DUMP"
read -r answer
[ "$answer" = "restore" ] || { echo "Aborted."; exit 1; }

docker compose -f "$COMPOSE_FILE" exec -T db sh -c \
  'pg_restore --clean --if-exists --no-owner --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$DUMP"
echo "Restore complete. Start the application again with:"
echo "  docker compose -f $COMPOSE_FILE up -d"
