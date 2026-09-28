# LeadFinder AI: Operations Guide

This guide is for TECOMSA administrators and any qualified developer who maintains LeadFinder. It assumes nothing
about the original developer.

## 1. Ownership checklist

TECOMSA must hold owner or administrator access to all of the following:

- [ ] The private Git repository (GitHub, GitLab or a self-hosted server) that holds this code
- [ ] The production server or cloud account running Docker
- [ ] The production `.env` file and all secrets in it
- [ ] The PostgreSQL superuser credentials
- [ ] The backup storage location (and an off-site copy)
- [ ] DNS and TLS certificates for the LeadFinder hostname

## 2. Production deployment

The server needs Linux with Docker Engine and the Docker Compose plugin, a DNS name, and a TLS reverse proxy (nginx,
Caddy, Traefik or a cloud load balancer).

```bash
git clone <tecomsa-repo-url> leadfinder && cd leadfinder
cp .env.example .env
# Set: ENVIRONMENT=production, COOKIE_SECURE=true, FRONTEND_URL=https://leadfinder.<domain>,
#      strong POSTGRES_PASSWORD, APP_SECRET, JWT_SECRET (≥32 random chars each)
chmod 600 .env

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec backend python -m scripts.create_admin --email admin@tecomsa.me --name "Admin Name"
```

Point the reverse proxy at `127.0.0.1:3000`. The backend and database have no public ports.

Example Caddyfile:

```
leadfinder.example.com {
    reverse_proxy 127.0.0.1:3000
}
```

### Deploying a new version

```bash
git pull
./scripts/backup_db.sh                                  # always back up first
docker compose -f docker-compose.prod.yml up -d --build # migrations run automatically on backend start
docker compose -f docker-compose.prod.yml ps
```

### Rolling back

```bash
git checkout <previous-tag-or-commit>
# If the new version added migrations, first downgrade the schema with the NEW code still checked out:
#   docker compose -f docker-compose.prod.yml exec backend alembic downgrade <previous_revision>
docker compose -f docker-compose.prod.yml up -d --build
```

If a migration cannot be reversed safely, restore the backup you took before deploying (section 4).

### Logs, health and restarts

```bash
docker compose -f docker-compose.prod.yml logs -f backend        # also: frontend, db, backup
docker compose -f docker-compose.prod.yml restart backend
curl -s http://127.0.0.1:3000/api/health                         # {"status":"ok","database":"ok"}
```

### Updating environment variables

Edit `.env`, then run `docker compose -f docker-compose.prod.yml up -d` to recreate the affected containers. Changing
`JWT_SECRET` signs out all users. `BACKEND_INTERNAL_URL` is fixed when the frontend is built, so changing it requires
`--build`.

## 3. Database access

The production database is **not** published on any port. Use one of these methods:

**Shell on the server**

```bash
docker compose -f docker-compose.prod.yml exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

**GUI tools (pgAdmin, DBeaver, DataGrip) through an SSH tunnel**

Add a localhost-only port to the `db` service, for example `ports: ["127.0.0.1:5432:5432"]`, then from your
workstation run:

```bash
ssh -N -L 15432:127.0.0.1:5432 user@leadfinder-server
# connect your tool to localhost:15432
```

A VPN or restricted-IP firewall rule are also acceptable. Never expose 5432 to the internet.

**Useful queries**

```sql
\dt                                                             -- list tables
SELECT pg_size_pretty(pg_database_size(current_database()));    -- database size
SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;  -- row counts
SELECT action, count(*) FROM audit_logs GROUP BY 1 ORDER BY 2 DESC;
SELECT * FROM pg_stat_activity WHERE datname = current_database();  -- active connections
```

**Read-only user** (for reporting or analysts)

```sql
CREATE ROLE leadfinder_readonly LOGIN PASSWORD '<strong-password>';
GRANT CONNECT ON DATABASE leadfinder TO leadfinder_readonly;
GRANT USAGE ON SCHEMA public TO leadfinder_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO leadfinder_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO leadfinder_readonly;
-- revoke later with:  DROP OWNED BY leadfinder_readonly; DROP ROLE leadfinder_readonly;
```

**Export data**

```bash
docker compose -f docker-compose.prod.yml exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "\copy (SELECT * FROM companies) TO STDOUT WITH CSV HEADER" > companies.csv
```

## 4. Backups and restore

**Automated:** the `backup` service in `docker-compose.prod.yml` runs `pg_dump` every `BACKUP_INTERVAL_SECONDS`
(default 24 h). It writes `./backups/<db>_<UTC timestamp>.dump` and deletes dumps older than `BACKUP_RETENTION_DAYS`
(default 14). Check it with `docker compose -f docker-compose.prod.yml logs backup`.

**Manual:** `./scripts/backup_db.sh` writes `./backups/leadfinder_<timestamp>_manual.dump`.

**Off-site copy (required):** `./backups` is on the same server as the database. Sync it to TECOMSA-owned storage,
such as an S3-compatible bucket or NAS, for example with a nightly `rclone sync ./backups remote:leadfinder-backups`.

**Restore**

```bash
docker compose -f docker-compose.prod.yml stop backend frontend
./scripts/restore_db.sh backups/<file>.dump            # asks you to type "restore"
docker compose -f docker-compose.prod.yml up -d
```

**Test restores monthly** on a separate machine or database so a real restore is never the first one:

```bash
docker run -d --name lf-restore-test -e POSTGRES_PASSWORD=test postgres:16-alpine
docker exec -i lf-restore-test sh -c 'until pg_isready -U postgres; do sleep 1; done; createdb -U postgres lf'
docker exec -i lf-restore-test pg_restore -U postgres -d lf --no-owner < backups/<file>.dump
docker exec lf-restore-test psql -U postgres -d lf -c "SELECT count(*) FROM companies;"
docker rm -f lf-restore-test
```

## 5. Git workflow

- `main`: production. Only tested, reviewed code is merged here. Tag releases, for example `v0.1.0`.
- `develop`: integration branch for ongoing work.
- Feature branches (`feature/odoo-check`) are merged into `develop` through pull or merge requests.
- Never commit `.env`, backups or credentials. `.gitignore` excludes them.

## 6. Troubleshooting

| Symptom | Check |
| --- | --- |
| Backend exits with `JWT_SECRET must be set…` | In staging and production both secrets must be ≥32 random characters. |
| Login works but you are sent straight back to `/login` | Over plain HTTP, `COOKIE_SECURE=true` stops the cookie from being stored. Use HTTPS, or set `false` for local development only. |
| `429 Too many login attempts` | Wait `LOGIN_RATE_LIMIT_WINDOW_SECONDS` (default 5 min), or restart the backend. |
| Frontend shows "Server error" | `docker compose logs backend`. Full stack traces are logged server-side and never sent to the browser. |
| `/api/*` returns 500 or ECONNREFUSED in the frontend logs | The backend is down, or `BACKEND_INTERNAL_URL` is wrong (production image: set at build time). |
| Tests refuse to run | `TEST_DATABASE_URL` must be set and the database name must end in `_test`. |
| `leadfinder_test` does not exist | It is created only when the dev Postgres volume is first initialised. Run `docker compose exec db createdb -U leadfinder leadfinder_test`. |
| Migration drift | `alembic check` from `backend/` reports model changes that have no migration. |
