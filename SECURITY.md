# LeadFinder: Security

LeadFinder holds TECOMSA's prospect data, decision-makers and their business contacts, TECOMSA's own CRM / contributed
contacts (some private to a salesperson) and sales feedback. This page explains how that data is protected and what
production requires. Deployment steps are in [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Production requirements

The backend **refuses to start** in `ENVIRONMENT=staging|production` when any of these is true:

- **App and session secrets:** `APP_SECRET` or `JWT_SECRET` is missing, shorter than 32 characters, a development default, or both are the same value.
- **Signing algorithm:** `JWT_ALGORITHM` is not HS256/HS384/HS512.
- **Database password:** it is a known default or shorter than 16 characters.
- **Cookies:** `COOKIE_SECURE=false`.
- **Origins:** `FRONTEND_URL` / `CORS_EXTRA_ORIGINS` include `*`, `localhost`, `127.0.0.1` or a non-https origin.
- **Demo accounts:** an active development demo account (`demo.*@example.com`) exists. `scripts/seed_dev.py` refuses to run outside development and test, and its password is published in this repository.

How production is laid out:

- **HTTPS:** HTTPS is mandatory. A TLS reverse proxy (nginx, Caddy, Traefik or a cloud load balancer) sits in front of the frontend on `127.0.0.1:3000`.
- **Client IP:** the proxy must set `X-Forwarded-For`. The backend trusts that header only from private networks (`FORWARDED_ALLOW_IPS`), so clients cannot forge their IP to dodge login rate limits.
- **Body size:** the backend refuses request bodies over 1 MB before parsing them (every body LeadFinder accepts is JSON and far smaller); a proxy limit of a few MB is enough.
- **Database exposure:** the database has no published port. Administrators reach it over an SSH tunnel or VPN.
- **Database accounts:** the backend connects as `APP_DB_USER`, a non-superuser role that owns only the LeadFinder database. `docker/postgres/init-prod/01-app-role.sh` creates it the first time the volume is initialised. `POSTGRES_USER` is the admin account, used for backups only.
  - **Upgrading an older volume:** the init script doesn't run, so create the role by hand, then change the owner of the database, the `public` schema and every table to it.
- **Containers:** both run as non-root users. Production images don't include test tooling. API docs (`/docs`, `/openapi.json`) are off in production.

Development stays convenient: plain HTTP, localhost origins and the dev compose file. The dev compose binds the database to 127.0.0.1. If you publish the dev frontend on your LAN (`0.0.0.0:3000`), anyone on that network can reach the login page, and session cookies travel unencrypted.

## Secrets

- **Where they live:** secrets are read from environment variables (`.env`, which git ignores) on the server only. They never appear in API responses, error messages, logs, the frontend bundle or the browser. Tests check this.
- **`.env.example`** holds placeholders only.
- **No contact-data provider keys** are used: LeadFinder calls no paid provider (Apollo, Lusha, …) and never fetches their sites.
- **Logs:** `httpx` request logging is turned down, because public-source lookups carry names in URLs.

### Rotate before production (names only)

| Secret | Why | How |
|---|---|---|
| `APP_SECRET`, `JWT_SECRET` | Development values exist on developer machines | `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Changing `JWT_SECRET` signs everyone out. |
| `POSTGRES_PASSWORD`, `APP_DB_PASSWORD` | The dev password is short and shared | Set new long random values before the first production start. Otherwise use `ALTER ROLE ... PASSWORD`. |
| `APOLLO_API_KEY`, `LUSHA_API_KEY` (if still in an old `.env`) | Used from development machines; no longer read | Revoke them at the provider and delete the lines from `.env`. |
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

| | Salesperson | Sales manager | Admin |
|---|---|---|---|
| Companies, people, contacts; research, corrections, sales feedback | ✓ | ✓ | ✓ |
| Find Leads searches | their own (others: 404) | all | all |
| TECOMSA / contributed contacts with visibility *managers* | only their own | ✓ | ✓ |
| Contacts with visibility *private* | owner only | owner only | owner only |
| Delete a company; remove a person on request (privacy) | ✗ | ✓ | ✓ |
| Users, audit log, system status | ✗ | user list only | ✓ |

- **Server-side checks:** every endpoint authorises on the server from the session's user. Hiding things in the frontend is never the protection.
- **Unknown request fields** are rejected (`extra="forbid"`).
- **Internal and contributed contacts** carry their owner and visibility on every email, phone and role; a public role a contribution matches stays public. Research never overwrites or deletes human-confirmed, TECOMSA CRM or contributed contacts.
- **Removal on request:** a manager can remove a person (roles, emails, phones, evidence); the person is then never researched or imported again at that company (only a hash of company + name is kept). A contributed source can be removed without touching public evidence.

## External data: fetching and imports

- **Website and source fetcher** (`app/services/discovery/fetch.py`):
  - only http/https on ports 80 and 443, with no credentials in the URL;
  - every address must be public: loopback, private, link-local and metadata, CGNAT, unique-local, IPv4-mapped/NAT64/6to4, internal host names and Docker services are all blocked;
  - the IP checked is the IP connected to, so DNS rebinding doesn't help;
  - redirects are re-checked at every hop, and proxy environment variables are ignored;
  - bounded page size with bounded gzip/deflate decompression (brotli/zstd refused), timeouts, robots.txt respected, per-host pacing.
- **Never fetched:** LinkedIn, Sales Navigator and contact-data vendors' sites; no login walls, CAPTCHAs or paywalls are bypassed. Mailbox (SMTP) checks are off by default and never send mail.
- **Contact imports** (`python -m app.services.contributions`, run by an administrator): CSV / XLSX / VCF / TXT, dry run by default, read without evaluating formulas; notes and home numbers are never imported; role mailboxes (info@, sales@) are never attached to a person.
- **XSS:** React escapes all text and nothing uses `dangerouslySetInnerHTML`. Links built from external data are rendered only if they're http(s). The production CSP denies framing, objects and other origins.

## Audit trail

- **Integrity:** audit entries are append-only. No endpoint edits or deletes them, and the reader endpoint is admin-only. The actor and timestamp always come from the server session and clock.
- **What's recorded:** logins (successful and failed: email, IP, reason), user changes, company and person corrections, contribution imports and removals, sales feedback events and privacy removals.
- **What's never recorded:** passwords, tokens, cookies or API keys.
- **Retention:** keep audit entries at least as long as the CRM data they describe. Back them up with the database.

## Backups

The `backup` service in `docker-compose.prod.yml` writes a daily `pg_dump` to `./backups` (14 days kept).

- **These files contain all prospect and contact data.** Keep them on encrypted storage that only administrators can read, copy them off the server, and test a restore regularly (see OPERATIONS.md §4).
- **Never commit dumps:** `backups/` and `*.dump` are git-ignored.

## Dependencies

Check before each release with `pip-audit -r backend/requirements.txt` and `npm audit --omit=dev` (in `frontend/`). Fix exploitable findings without blindly jumping major versions.

## Reporting a problem

Report suspected vulnerabilities privately to the LeadFinder administrators at TECOMSA, not in a public issue.
