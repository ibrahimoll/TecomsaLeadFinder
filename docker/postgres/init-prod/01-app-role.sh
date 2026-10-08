#!/bin/sh
# Production: LeadFinder connects as its own NON-superuser role that owns only its database.
# POSTGRES_USER stays the administrative superuser (backups, maintenance) and is never used by the app.
# Runs once, when the Postgres volume is first initialised.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_user="$APP_DB_USER" -v app_pass="$APP_DB_PASSWORD" -v db="$POSTGRES_DB" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_pass' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER DATABASE :"db" OWNER TO :"app_user";
ALTER SCHEMA public OWNER TO :"app_user";
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
