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

**Uploaded import files:** the original Odoo export files live in the `imports` Docker volume
(`/app/storage/imports`). All imported data is in PostgreSQL, so the database backup is what matters. Keep the files
only if you want the original exports as an audit trail. They contain CRM data, so protect them like the database.

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

## 5b. People sources (Lebanon source pack)

People research needs no paid API: no Apollo, Lusha, ZoomInfo, Brave or other search keys. Public Lebanese sources are
read once and kept locally, then matched to companies without further requests. The sources are listed in
`backend/app/services/people/external/lebanon/sources.json`.

```bash
# Run whenever you want to pick up new source versions (not scheduled). Due sources are read again; only new or
# changed documents are parsed and applied.
docker compose exec backend python -m scripts.lebanon_sources refresh
docker compose exec backend python -m scripts.lebanon_sources status
# An official extract (e.g. Commercial Register) or a licensed directory file. Columns:
# company,person,title,published,url,domain,registration_number,email,phone
docker compose exec backend python -m scripts.lebanon_sources ingest-file commercial_register /path/extract.csv
```

- The Commercial Register website (cr.justice.gov.lb) is never queried, because its terms forbid commercial use of
  its data. Use official extracts as files instead.
- Subscription directories (5INDEX, Yelleb, Infobel, Kompass, IFP) are never fetched. Their licensed exports are
  imported as files (section 5d, *Licensed directory exports*), not through this pack.
- Common Crawl and Wikidata run per company, only while people are missing. Their answers are cached in
  `external_search_cache`.
- Web search (`PEOPLE_SEARCH_PROVIDER`) is optional and set to `none` by default.
- **Adding a simple source is configuration only.** Add an entry to `sources.json` with `"parser": "configured"`
  and an `extract` block: `table` (HTML tables), `lines` (text lines, optionally with section headings), `xpath`
  (repeated items), `regex` (embedded data) or `bios` (board pages). People are created only when a name, title and
  company are all explicit.
- **Why a company has no people.** `company_gap_reasons` records the measured reasons (no website, no external
  person source, Arabic/Latin possible match, Common Crawl error…). `companies.next_research_eligible_at` is the
  retry cooldown. A company is researched again sooner when one of its sources changes or it gains an alias.
- **Common Crawl reliability.** Every index lookup is recorded in `source_lookups` (status, failure reason,
  timing, cache hit).
- **Sources deliberately not used:**
  - HORECA Lebanon and Hospitality News: their robots.txt blocks crawlers.
  - Beirut Business Forum: its terms forbid scraping.
  - Order of Engineers and CCIB: their pages sit behind a challenge.
  - Commercial Register: file import only.
  - BDL: blocks automated access.
  - 5INDEX, Yelleb, Infobel, Kompass, IFP: licensed exports as files only (section 5d).

## 5c. Direct company search (Find Leads › Search for a company)

- While the user types, suggestions come from LeadFinder's own database only (`GET /companies/search`). No public source is called per keystroke.
- **Search** / Enter calls `POST /companies/lookup`:
  - The database is searched first: domain, identifier, exact name, legal name, alias (Arabic, French, English), the name without legal form or place, brand, transliteration and typos.
  - If nothing strong is known, the permitted public sources are tried, cheapest first, for at most 20 seconds: the local source corpus, then the Overture / OpenStreetMap / dataset extracts and the website itself (for a domain), then Wikidata.
  - A company is created only on strong source evidence, through discovery's duplicate resolution. Its research is queued at priority 3.
  - **Web search**: the lookup also runs one real web search per query (`COMPANY_SEARCH_PROVIDER=auto`). The
    engines are tried in order, each the next one's backup when it fails or finds nothing:
    1. **SearXNG** (the `searxng` compose service, `SEARXNG_URL`; settings in `docker/searxng/settings.yml`). It is
       free and comes close to Google's coverage. It reads search engines' result pages, which their terms forbid,
       so it is for internal use only; a licensed API replaces it if LeadFinder is sold. From the office (2026-10-13)
       only Yahoo answers; Google, DuckDuckGo, Qwant and Brave block the IP. Check the engines with
       `docker compose logs searxng`.
    2. **LangSearch** (`LANGSEARCH_API_KEY`, a free daily allowance).
    3. **Tavily** (`TAVILY_API_KEY`, 1,000 free a month).

    A page about the company elsewhere is offered with **View page**, never created on its own. That covers Facebook,
    Instagram and directory pages, and a site that is not verified as its own. Only pages whose title carries every
    word of the searched name are kept; single posts, reels and news headlines are skipped.
    `docker-compose.prod.yml` has no SearXNG service, so production uses the API keys. Its results are cached for
    `SEARCH_CACHE_DAYS`, so a repeated search spends nothing. The company's own website is verified as before. Its
    pages on platforms (Facebook, Instagram, Google Maps, directories) whose title carries the searched name are
    offered with a "View page" link. They are never created on their own; **Add company** creates one. People research
    does not use it (`PEOPLE_SEARCH_PROVIDER` stays `none`), so background jobs never spend the free searches.
  - Several matching entities are returned as `ambiguous`, and the user picks one (`POST /companies/lookup/{id}/select`).
- Every lookup is logged in `company_lookups`. That table holds the analytics, a 24-hour negative cache, and the candidates the user can pick from.
- The query is read as free text first (`services/query_understanding.py`). For example "hotel called Aleph in Byblos" becomes name Aleph, city Byblos, industry Hospitality. The database is searched with the words as typed, then with the name they contain.
- Unknown companies are then looked for in this order:
  1. The source corpus, with the sources for the query's industry first.
  2. The map extracts.
  3. GLEIF, used live for other countries.
  4. Web discovery (`services/web_discovery.py`).
  5. Wikidata.
- Web discovery runs at zero cost. It checks which candidate domains exist in DNS, then verifies each website: the company's name must appear on it, and so must the country (TLD, phone, city). Parked pages, directories and the same name abroad are rejected. A licensed search API plugs into the same provider interface only when one is configured.
- Every network source sits behind a circuit breaker. A search waits at most 4 seconds for its turn at Wikidata.
- `company_domains` keeps current, alternate and historical domains, so any of them finds the company.
- After a change to the name-key rules, rebuild the keys with `python -m app.services.company_search reindex`.
- Holdout: `python -m scripts.search_holdout run holdout LABEL`. Run it only on an untouched set.
- The API builds an in-memory index of the cached extracts in the background at start. It takes about 15 seconds and roughly 250 MB for Lebanon.
- Benchmark: `python -m scripts.search_benchmark run LABEL [--unknown]`. Run it on a disposable copy of the benchmark database, because a lookup creates companies.

## 5d. People + contact acquisition (Step 6.1)

- **TECOMSA internal contacts** (Odoo contacts / customers / leads, business cards, meeting contacts: CSV or XLSX).
  Template: `docs/contact_import_template.csv` (any subset of its columns; Odoo's own export headers — *Name / Display
  Name, Related Company / Company Name, Job Position, Email, Phone, Mobile, Website, Country, Salesperson, Last Updated
  on* — are recognised). Required: a company column, a contact name and a job position.
  1. Dry run (writes nothing; the report is exactly what an apply does):
     `docker compose exec backend python -m app.services.contributions /tmp/contacts.csv ODOO_CRM [--owner EMAIL] [--visibility organization|managers|private]`
  2. Review the report: companies exact / strong / possible / unmatched, people exact / strong / possible / new,
     conflicts with colleague-confirmed titles, rejected rows, phones without a country code (`review` lists each).
  3. Back up the database (section 4), then the same command with `--apply`. Re-running the same file changes nothing.
  Systems: ODOO_CRM, CSV_IMPORT, BUSINESS_CARD, SALES_CONFIRMED (every e-mail confirmed), MEETING_CONTACT.
  Rows attach to existing companies only. Visibility: `organization` (everyone), `managers` (the owner + managers /
  admins), `private` (the owner only).
  The same command takes business cards (`.vcf`, channel BUSINESS_CARD), professional e-mail signatures (`.txt`, one
  signature per blank-line block, EMAIL_SIGNATURE) and meeting contacts (rows, MEETING_CONTACT: attendance links a
  person to an e-mail, never a title; unknown people are not created). One contact can also be added on a company's
  People tab (*Add business contact*). A contributed source is removed with `contributions.suppress(source_id)`:
  only what it alone stated goes; public evidence stays; it is never imported again.
- **Licensed directory exports** (5INDEX, Yelleb Data Hub, later InfobelPRO / Kompass / IFP: files TECOMSA is
  licensed to use; the directories' websites are never accessed). Settings › *Directory imports* (managers / admins):
  pick or type the directory, upload its .xlsx / .csv export (≤ 10 MB) → the detected columns (English or French
  headers: *Company / Société / Raison sociale*, *Contact / Contact person / Manager / General Manager / Owner /
  Gérant*, *Title / Position / Fonction*, *Phone / Tel / Téléphone*, *Mobile / Cell / GSM / Portable*, *WhatsApp /
  WhatsApp number / WA* (kept apart from the mobile), *E-mail*, *Website / Site web*, *Sector / Activity / Activité*,
  *City / Ville*, *Address / Adresse*; *Fax* ignored; any other column listed as not recognised) and what the import
  would add (new / existing companies, people, mobiles, WhatsApp, other numbers, e-mails, skipped rows with reasons)
  → *Import*. Sample: `docs/5index_import_sample.csv` (fictional). Bigger files, same dry run / apply:
  `docker compose exec backend python -m app.services.contributions /tmp/export.xlsx LICENSED_DIRECTORY --directory
  Yelleb --owner EMAIL [--apply]`.
  A company LeadFinder lacks is created through discovery's duplicate resolution (never twice; a deleted company is
  not re-created); a known one is only completed (contacts added, blank phone / e-mail filled). The Tel column is the
  company's line, the Mobile / WhatsApp columns the named person's (the company's on a row naming nobody); a person
  column named after a role (*General Manager*, *Owner*, *Gérant*) is the title when the row has none; a person
  without any title is not created. Every record is a source named `<directory> (licensed directory)`; its contacts
  carry the `licensed` provenance, are kept by retention and go with their import: the history's *Remove* deletes
  what only that import added (contacts, people, the companies it created that nothing else describes) — so one
  directory's data can be removed alone, and the file can be imported again. The same person from two directories is
  one person (corroborated). *Coverage per directory* (same page, `GET /imports/directory/coverage`): per directory,
  people, people with a mobile / WhatsApp / e-mail, companies with a number — what each states today. Check each
  directory's licence terms before using its data beyond TECOMSA's own sales team.
- **Sales feedback**: People tab › *Feedback…* per person (or `POST /companies/{id}/contact-feedback`): email
  delivered / replied / bounced, phone correct / wrong / company line, correct person / left / wrong person. Applied at
  once; research never undoes it.
  A mail system can report deliveries / bounces / replies by address: `POST /companies/contact-events`
  `{"event": "delivered" | "hard_bounce" | "soft_bounce" | "replied", "email": ..., "event_key": <its message id>}` —
  applied once per event_key. Nothing is ever sent to test an address.
- **Public vs TECOMSA metrics**: `python -m scripts.contact_coverage measure LABEL [--sales] [--public]`: `--public` counts
  what LeadFinder discovers on its own (no internal data, no colleague confirmations); without it, public + TECOMSA.
  Both include department coverage and the feedback rates (predicted → delivered / replied / bounced).
- **Source value**: `python -m scripts.source_inventory LABEL` (every source: people, contacts, contactable companies);
  `python -m scripts.contact_coverage measure LABEL [--sales]` (benchmarks, with per-source contribution).
- **Mailbox signatures** (Zoho, or any IMAP mailbox the owner connects on purpose): `app.services.mailbox`
  connects read-only, keeps the sender's own signature block from business e-mails (not colleagues, newsletters,
  no-reply senders or quoted replies), and sends it through the EMAIL_SIGNATURE pipeline. It runs as a dry run
  unless you pass `--apply`. Enable IMAP in Zoho Mail and use an application-specific password (you can revoke it
  afterwards):
  `MAILBOX_PASSWORD=... docker compose exec -e MAILBOX_PASSWORD backend python -m app.services.mailbox LOGIN [--days 365] [--owner EMAIL] [--apply]`
- **Mailbox verification** (`EMAIL_SMTP_VERIFICATION=true`). Run it only from a host with a static IP that is not
  on a blocklist and whose reverse DNS matches `EMAIL_SMTP_HELO`. Set `EMAIL_SMTP_MAIL_FROM` to a real TECOMSA
  mailbox (e.g. `verify@tecomsa.me`), because backscatter filters refuse the null sender. Measured on 2026-10-08
  from the office line (82.146.184.242): the IP is on Spamhaus's dynamic-IP list, so Microsoft 365 and Zoho
  refuse every check; Lebanese bank gateways (BLC, Credit Libanais) drop the connection; Bank of Beirut and Arope
  are catch-all. Result: 0 verified.
- **Removing a person on request** (privacy / right to erasure): managers and admins use
  `POST /companies/{id}/people/{person_id}/remove {"reason": "..."}`. It deletes the person, their roles, emails,
  phones and evidence. Research and imports never add them again at that company. Only a hash of the company and
  the name key is kept, and the audit log stores the person id and reason, never the name. It cannot be undone.
- **Retention**: the worker deletes, once a day, any publicly researched role that no source has seen for
  `CONTACT_RETENTION_DAYS` (default 730; `0` = never), then every person left without a role. TECOMSA's own data
  (Odoo, contributed), colleague corrections and confirmed contacts are kept.
- **Common Crawl** is read from its static index files on data.commoncrawl.org (the index server is unreachable from
  this network); lookups take 10–50 s each, so they run inside deep research only, bounded by
  `COMMONCRAWL_BUDGET_SECONDS`.

## 5f. Sales pitches (Claude)

- **What**: the Opportunity tab's *Write pitch* (per product: Odoo / Frinzo / IT) asks Claude (`PITCH_MODEL`,
  default `claude-opus-5-5`, effort `PITCH_EFFORT` = medium) for why the company needs it, 3-5 points, a call opener,
  a first WhatsApp message and likely objections. Claude gets LeadFinder's facts only (fit reasons and evidence,
  description, industry, signals, people's names and titles) - never a phone number or e-mail.
- **Cost**: one call per company and product, about a few cents; the pitch is saved (`opportunity_analysis`) and
  reused for `PITCH_CACHE_DAYS` (30). *Write a new one* makes a new call. Every call is audited
  (`company.pitch_written`, with token counts).
- **Setup**: `ANTHROPIC_API_KEY=...` in `.env` (Claude Console > API keys), then restart the backend. The image needs
  the `anthropic` package (`requirements.txt`): rebuild with `docker compose build backend worker` after pulling.
- Refusals fall back server-side (`fallbacks: "default"`); a refused or unreadable answer stores nothing.

## 5e. Lusha (paid people + contact reveal)

- **Key**: every Lusha plan, Free included, comes with an API key (Lusha help centre). In the Lusha dashboard open
  *API Hub* (left sidebar) › *Copy API key* (https://dashboard.lusha.com/api/manage-api-keys). LeadFinder calls API V3
  (`https://api.lusha.com/v3/...`); an account without V3 access gets 403 "V3 API access is not enabled": ask Lusha.
- **Env** (`.env`, then restart backend + worker): `LUSHA_API_KEY` (empty = off; the People tab says "Lusha not
  configured"; the key is never logged or returned), `LUSHA_MONTHLY_CREDIT_BUDGET` (hard cap on LeadFinder's Lusha
  credits per calendar month, enforced server-side; `0` = no cap), optional `LUSHA_SEARCH_SIZE` (people per company
  search, default 25), `LUSHA_SEARCH_CACHE_DAYS` (default 30), `LUSHA_TIMEOUT_SECONDS`, `LUSHA_BASE_URL`.
- **One seat for the team**: `LUSHA_PHONE_ONLY` (default `true`: only *Get number*, an email reveal is refused) and
  `LUSHA_USER_DAILY_REVEALS` (paid reveals per user per day, default 20, `0` = no cap; an already revealed person is
  free and does not count). A person LeadFinder already has a number for shows *Number in LeadFinder*, and a reveal of
  them is refused before Lusha is called.
- **Costs** (Lusha docs, 2026-10): a work email 1 credit, a phone 5 credits (per revealed data point, billed once per
  account: a person already revealed costs 0); a search is billed per result (`api_search`), so *Search Lusha* is a
  confirmed click too and its list is kept for `LUSHA_SEARCH_CACHE_DAYS`. Lusha's per-account price list:
  `GET https://api.lusha.com/v3/account/usage` (`pricing`). The waterfall (third-party providers, extra credits) is
  turned off on every reveal.
- **How it works**: People tab › *From Lusha* › *Search Lusha* (confirm) lists the people Lusha has (by the company's
  domain, else its name) with email / phone masked and what Lusha has. *Reveal email* / *Reveal phone* shows the cost
  and the credits left, and only on confirm calls Lusha for that one field of that one person. The result is saved as
  the person (same name = same person) + title + work email / phones (provenance `lusha`, visible to everyone at
  TECOMSA, kept by retention) and shown in clear to every user from then on: nobody pays twice. A person removed on
  request is never revealed. Nothing is revealed in bulk, automatically or by background research.
- **Free-text search** (one box above the *From Lusha* list, like the Lusha extension on a company page): type
  *IT*, *IT manager*, *CFO*, *marketing*… (empty = everyone at the company; optional *Has phone*). Words that are
  exactly one of Lusha's departments (*IT* = Information Technology, *finance*, *marketing*…) or seniorities
  (*director*, *manager*, *c-level*…) search that whole department / level; anything else is a job title (Lusha
  combines filter types with AND, so never both). The value lists come from Lusha's filter endpoints
  (`/v3/contacts/prospecting/filters/…`, cached a day; if they fail, the words are a job title). Enter / *Search*:
  the same search (words with case and spacing ignored, toggle, page) within `LUSHA_SEARCH_CACHE_DAYS` shows again
  free without asking; otherwise it is confirmed with "up to `LUSHA_SEARCH_SIZE` credits". *Next page* is another
  confirmed search.
- **Ledger**: table `lusha_requests` (every search / reveal: who, company, status, credits; pending rows are written
  before the call, so a double click or second tab pays once). Managers / admins: `GET /lusha/ledger`; everyone:
  `GET /lusha/credits` (this month's spend, budget left, Lusha's balance). Audit actions `lusha.*`.
- **Licence**: Lusha's terms may restrict storing revealed data or showing it to people outside the subscribing
  company. Check them before using this for anyone but TECOMSA's own team.

## 5g. Owner lock

The owner can stop the whole website with a key only they know. The key is typed into a hidden prompt; LeadFinder
stores only its Argon2 hash, so nobody (admins, developers, AI assistants) can read it back. While locked, every API
request except `/health` returns a bare 503 "Service Unavailable" and the website shows only a 503 error page (login
included; nothing of LeadFinder loads, nothing names the lock).

```
docker compose exec backend python -m scripts.owner_lock set      # once: choose the key (min. 12 characters)
docker compose exec backend python -m scripts.owner_lock lock     # stop the website
docker compose exec backend python -m scripts.owner_lock unlock   # start it again
docker compose exec backend python -m scripts.owner_lock change   # new key (needs the current one)
docker compose exec backend python -m scripts.owner_lock status
```

Keep the key in a password manager: a lost key cannot be recovered (a database administrator can only remove the
lock with `DELETE FROM owner_lock`). The lock protects against app users, not against whoever controls the server.

## 6. Troubleshooting

| Symptom | Check |
| --- | --- |
| A search fails with "Overture data could not be queried" | The backend needs outbound HTTPS to `stac.overturemaps.org`, `overturemaps-us-west-2.s3.us-west-2.amazonaws.com` and (first run only, for DuckDB's `httpfs`) `extensions.duckdb.org`. Once a release is cached, searches work offline from the cache. |
| Searches are "Partially completed" with an OpenStreetMap error | The backend could not download the extract from `download.geofabrik.de`. Overture results are still saved; OSM is retried after 15 minutes. An older cached extract is used when there is one. |
| The first search is slow | The first search of each Overture release downloads the country extract (about a minute). The cache lives in the `discovery` volume (`DISCOVERY_CACHE_DIR`). |
| Many websites show "Blocks visits" or "Empty page" | Some sites refuse automated visits (403 / bot challenges) or need JavaScript; LeadFinder does not bypass either. The backend needs outbound HTTP/HTTPS to company websites. |
| The People tab keeps "Searching…" | `GET /companies/{id}` returns `people_research.state`; the UI polls only while it is `website_*` / `deep_*`. Every stage ends: deep research stops at `EXTERNAL_JOB_SECONDS` (120, `timed_out`); Common Crawl at `COMMONCRAWL_BUDGET_SECONDS` (45) and, once its index is unreachable, is skipped for every company for `COMMONCRAWL_DOWN_SECONDS` (600). The worker's watchdog (every minute) finishes a job past its limit + 60 s as `timed_out`, a dead worker's job as interrupted, and a company stage left queued / researching with no job. Worker logs: `company=… pipeline=… job=… stage=… status=a->b people=… execution=… queue_wait=…` (queue wait is not research time). |
| A search stays "Searching" after a restart | Runs execute in the backend process; a restarted backend marks interrupted runs as failed / partially completed at startup. |
| Backend exits with `JWT_SECRET must be set…` | In staging and production both secrets must be ≥32 random characters. |
| Login works but you are sent straight back to `/login` | Over plain HTTP, `COOKIE_SECURE=true` stops the cookie from being stored. Use HTTPS, or set `false` for local development only. |
| `429 Too many login attempts` | Wait `LOGIN_RATE_LIMIT_WINDOW_SECONDS` (default 5 min), or restart the backend. |
| Frontend shows "Server error" | `docker compose logs backend`. Full stack traces are logged server-side and never sent to the browser. |
| `/api/*` returns 500 or ECONNREFUSED in the frontend logs | The backend is down, or `BACKEND_INTERNAL_URL` is wrong (production image: set at build time). |
| Tests refuse to run | `TEST_DATABASE_URL` must be set and the database name must end in `_test`. |
| `leadfinder_test` does not exist | It is created only when the dev Postgres volume is first initialised. Run `docker compose exec db createdb -U leadfinder leadfinder_test`. |
| Migration drift | `alembic check` from `backend/` reports model changes that have no migration. |
| Upload says no Company Name or Contact Name column was detected | The export's headers are not recognised. The message lists the columns found; re-export from Odoo with the Name / Company columns, or rename the headers. |
