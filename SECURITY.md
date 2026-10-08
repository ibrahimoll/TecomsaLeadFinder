# LeadFinder AI: Security

LeadFinder holds TECOMSA's prospect and CRM data, salespeople's private leads, decision-maker contact details,
and API credentials for Odoo, Apollo and Lusha. This page explains how that data is protected and what
production requires. Deployment steps are in [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Production requirements

The backend **refuses to start** in `ENVIRONMENT=staging|production` when any of these is true:

- **App and session secrets:** `APP_SECRET` or `JWT_SECRET` is missing, shorter than 32 characters, a development default, or both are the same value.
- **Signing algorithm:** `JWT_ALGORITHM` is not HS256/HS384/HS512.
- **Database password:** it is a known default or shorter than 16 characters.
- **Cookies:** `COOKIE_SECURE=false`.
- **Origins:** `FRONTEND_URL` / `CORS_EXTRA_ORIGINS` include `*`, `localhost`, `127.0.0.1` or a non-https origin.
- **Integration URLs:** `ODOO_BASE_URL` or `APOLLO_WEBHOOK_BASE_URL` is not https.
- **Demo accounts:** an active development demo account (`demo.*@example.com`) exists. `scripts/seed_dev.py` refuses to run outside development and test, and its password is published in this repository.

How production is laid out:

- **HTTPS:** HTTPS is mandatory. A TLS reverse proxy (nginx, Caddy, Traefik or a cloud load balancer) sits in front of the frontend on `127.0.0.1:3000`.
- **Client IP:** the proxy must set `X-Forwarded-For`. The backend trusts that header only from private networks (`FORWARDED_ALLOW_IPS`), so clients cannot forge their IP to dodge login rate limits.
- **Body size:** set the proxy's body limit to about 25 MB (`client_max_body_size 25m`). The backend also refuses bodies over 1 MB, or over `IMPORT_MAX_BYTES` for uploads, before parsing them.
- **Database exposure:** the database has no published port. Administrators reach it over an SSH tunnel or VPN.
- **Database accounts:** the backend connects as `APP_DB_USER`, a non-superuser role that owns only the LeadFinder database. `docker/postgres/init-prod/01-app-role.sh` creates it the first time the volume is initialised. `POSTGRES_USER` is the admin account, used for backups only.
  - **Upgrading an older volume:** the init script doesn't run, so create the role by hand, then change the owner of the database, the `public` schema and every table to it.
- **Containers:** both run as non-root users. Production images don't include test tooling. API docs (`/docs`, `/openapi.json`) are off in production.

Development stays convenient: plain HTTP, localhost origins and the dev compose file. The dev compose binds the database to 127.0.0.1. If you publish the dev frontend on your LAN (`0.0.0.0:3000`), anyone on that network can reach the login page, and session cookies travel unencrypted.

## Secrets

- **Where they live:** secrets are read from environment variables (`.env`, which git ignores) on the server only. They never appear in API responses, error messages, logs, the frontend bundle or the browser. Tests check this.
- **`.env.example`** holds placeholders only.
- **Provider keys** are sent only to their own provider. The Odoo key goes only to the configured `ODOO_BASE_URL`; users can never supply integration URLs or credentials.
- **Logs:** `httpx` request logging is turned down, because provider lookups carry names in URLs. The single-use Apollo webhook token is removed from access logs.

### Rotate before production (names only)

| Secret | Why | How |
|---|---|---|
| `APP_SECRET`, `JWT_SECRET` | Development values exist on developer machines | `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Changing `JWT_SECRET` signs everyone out. |
| `POSTGRES_PASSWORD`, `APP_DB_PASSWORD` | The dev password is short and shared | Set new long random values before the first production start. Otherwise use `ALTER ROLE ... PASSWORD`. |
| `APOLLO_API_KEY` | Has been used from development machines | Regenerate in Apollo → Settings → API, then update `.env`. |
| `LUSHA_API_KEY`, `ODOO_API_KEY` | When configured | Regenerate in the provider or Odoo (Preferences → Account Security). |
| Dev and test account passwords | Published in scripts and docs | Never create these accounts in production. Deactivate any that exist. |

If a secret leaks: rotate it at the provider first, update `.env`, restart the backend, then review `audit_logs` and the provider's usage dashboard for the exposure window.

## Authentication and sessions

- **Passwords:** hashed with Argon2id (argon2-cffi). 10 to 256 characters. Never logged, never returned.
- **Login:**
  - Unknown email, wrong password and inactive account all get the same message, and take about the same time.
  - Rate limits are per email (10 attempts per 5 minutes) and per client IP (×5). The limiter lives in memory, per process.
- **Sessions:**
  - Each session is a server-side row (`user_sessions`) referenced by a signed token in the `lf_session` cookie: HttpOnly, SameSite=Lax, Path=/, Secure in production, 8 hours.
  - Logout, deactivation and password changes revoke sessions server-side, so a copied cookie stops working.
  - Expired, forged or revoked tokens are refused on every request.
- **CSRF:** any POST, PUT, PATCH or DELETE that carries the session cookie must come from LeadFinder's own origin, checked server-side with `Origin` / `Sec-Fetch-Site`. Together with SameSite=Lax and JSON-only bodies, cross-site requests can't act on a user's session.

## Roles and data isolation

| | Sales agent | Sales manager | Admin |
|---|---|---|---|
| Own discovered leads, research, decision-makers, enrichment, activities, opportunity | ✓ | ✓ (team) | ✓ |
| Colleagues' private leads | ✗ (404: not even their existence) | ✓ | ✓ |
| Odoo-protected companies | Identity and protection reason only | Full CRM detail | Full CRM detail |
| CRM records / Odoo contacts pages | ✗ | ✓ | ✓ |
| Imports | ✗ | If `MANAGERS_CAN_IMPORT` | ✓ |
| Users, audit log, integration status, deleting searches | ✗ | ✗ | ✓ |

- **Server-side checks:** every endpoint authorises on the server from the session's user. Hiding things in the frontend is never the protection.
- **Unknown request fields** (`role`, `owner_id`, `created_by`, `crm_status`, Odoo ids …) are rejected (`extra="forbid"`).
- **Ownership:** a company belongs to its owner (or, if it has none, its creator). Releasing it or reassigning the lead removes the previous person's rights.
- **Protected companies:** agents can't edit a protected company's identity fields (that would remove the protection), and they see only why it's protected, not the CRM's contacts, revenue or lost reasons.

## External data: crawler, imports, providers

- **Website crawler** (`app/services/research/fetch.py`):
  - only http/https on ports 80 and 443, with no credentials in the URL;
  - every address must be public: loopback, private, link-local and metadata, CGNAT, unique-local, IPv4-mapped/NAT64/6to4, internal host names and Docker services are all blocked;
  - the IP checked is the IP connected to, so DNS rebinding doesn't help;
  - redirects are re-checked at every hop (5 at most), and proxy environment variables are ignored;
  - limits: 2 MB per page, with bounded gzip/deflate decompression and brotli/zstd refused; timeouts; HTML only; page and depth caps.
  - Crawl4AI only parses HTML that LeadFinder has already fetched.
- **Imports:**
  - CSV or XLSX only, checked by magic number;
  - 20 MB and 50,000 rows at most, 300 columns at most, a cap on blank rows;
  - zip-bomb checks before opening a workbook, which is read without evaluating formulas;
  - stored under random server-generated names outside any web root; the uploaded file name is only shown, never used as a path.
- **CSV exports:** values that start with `= + - @`, a tab or a carriage return are made inert (only real phone numbers keep their leading `+`).
- **XSS:** React escapes all text and nothing uses `dangerouslySetInnerHTML`. Links built from external data (websites, LinkedIn, sources, Odoo) are rendered only if they're http(s). The production CSP denies framing, objects and other origins.
- **Paid providers (Apollo, Lusha):**
  - off by default (`PAID_ENRICHMENT_ENABLED`);
  - every call goes in the ledger;
  - the monthly budget is checked under a database lock;
  - a database unique index allows one live request per person, action and version, so double clicks and concurrent requests make one paid call;
  - each user has a daily cap (`PAID_ENRICHMENT_USER_DAILY_LIMIT`);
  - buying known data again needs a manager.
  - Apollo phone webhooks use a 256-bit, single-use token stored as a hash, so a replay gets 404.
- **Odoo:** the URL, database, login and key come only from server configuration. Users can't choose Odoo partner or opportunity IDs except from the candidates LeadFinder found.

## Audit trail

- **Integrity:** audit entries are append-only. No endpoint edits or deletes them, and the reader endpoint is admin-only. The actor and timestamp always come from the server session and clock.
- **What's recorded:** logins (successful and failed: email, IP, reason), user changes, imports, claims and releases, research and enrichment requests, and sales actions.
- **What's never recorded:** passwords, tokens, cookies or API keys.
- **Retention:** keep audit entries at least as long as the CRM data they describe. Back them up with the database.

## Backups

The `backup` service in `docker-compose.prod.yml` writes a daily `pg_dump` to `./backups` (14 days kept).

- **These files contain all customer and contact data.** Keep them on encrypted storage that only administrators can read, copy them off the server, and test a restore regularly (see OPERATIONS.md §4).
- **Never commit dumps:** `backups/` and `*.dump` are git-ignored.

## Dependencies

Check before each release with `pip-audit -r backend/requirements.txt` and `npm audit --omit=dev` (in `frontend/`). Fix exploitable findings without blindly jumping major versions.

## Reporting a problem

Report suspected vulnerabilities privately to the LeadFinder administrators at TECOMSA, not in a public issue.
