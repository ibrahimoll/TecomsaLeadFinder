# TECOMSA LeadFinder AI

Internal B2B sales intelligence platform for TECOMSA (Frinzo, Odoo ERP and IT Solutions), starting with the
Lebanese market.

**Current state: Phase 1 (automatic company discovery).** LeadFinder has:

- authentication, users and roles
- a company database with deterministic duplicate protection
- an **Odoo import center**: contacts and CRM leads/opportunities from CSV/XLSX, with automatic column detection,
  preview, duplicate detection, import history and deletion (with or without the imported data)
- a TECOMSA relationship status on every company, so companies TECOMSA already knows are never treated as new prospects
- CRM records and sales-team views, campaigns, contacts, and a full audit trail
- **Find companies**: automatic discovery of Lebanese companies by industry and area from free public data
  (Overture Maps Places, plus OpenStreetMap), with every result checked against LeadFinder and TECOMSA's Odoo
  data before anything is saved

It does **not** call the Odoo API, Lusha or any AI provider, and it never shows simulated results.

| Document | Contents |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture, database schema, matching and protection rules, API, UI system |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Production deployment, database access, backups and restore, troubleshooting |

---

## 1. Technical architecture

```
Browser ──► Next.js (frontend, :3000) ──/api/* proxy──► FastAPI (backend, :8000) ──► PostgreSQL 16
```

- **Frontend:** Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS (one token-based design system)
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Pydantic 2, Alembic, openpyxl for XLSX parsing
- **Database:** PostgreSQL 16
- **Auth:** email + password (Argon2id hashes), server-side sessions, signed token in an httpOnly cookie
- **Runtime:** Docker Compose (development and production files). No Redis, queues or paid services.

The browser only ever talks to the Next.js server, which forwards `/api/*` to FastAPI. The session cookie is
therefore same-origin and the backend is never exposed directly.

```
.
├── backend/
│   ├── app/
│   │   ├── api/               Routes and dependencies (auth, role checks, pagination)
│   │   ├── core/              Settings, security, rate limiting, domain exceptions
│   │   ├── models/            ORM models (companies, odoo, salesperson, import_run, …)
│   │   ├── schemas/           Pydantic request/response models
│   │   ├── services/          Business logic: imports, matching, relationship status, permissions
│   │   └── integrations/      odoo/ and lusha/ API interfaces (disconnected in Phase 0)
│   ├── migrations/            Alembic migrations (0001 foundation, 0002 Odoo import foundation)
│   ├── scripts/               create_admin.py, seed_dev.py, sample_odoo_files.py
│   ├── storage/imports/       Uploaded import files (git-ignored; not the datastore)
│   └── tests/                 pytest suite (separate test database)
├── frontend/
│   ├── app/                   Pages
│   ├── components/ui/         Design-system primitives (tables, forms, tabs, dialogs, states)
│   ├── components/            App shell, forms, status badges, activity timeline
│   ├── lib/                   API client, URL-state hooks, constants, formatting
│   └── types/                 Shared TypeScript types
├── samples/                   FICTIONAL Odoo export files for trying the import workflow
├── docker/postgres/init/      Dev-only DB init (creates the test database)
├── scripts/                   Database backup / restore scripts
├── docker-compose.yml         Development stack
├── docker-compose.prod.yml    Production stack (+ scheduled backups)
└── .env.example               Environment template
```

## 2. Requirements

- Docker Desktop (or Docker Engine) with Docker Compose v2, **or**
- For running without Docker: Python 3.12+, Node.js 20+ (22 LTS recommended), PostgreSQL 16

## 3. Quick start (Docker)

```bash
cp .env.example .env
# Edit .env: at least set POSTGRES_PASSWORD (and the same password in DATABASE_URL / TEST_DATABASE_URL)

docker compose up --build
```

On startup the backend runs `alembic upgrade head`. Then:

| Service | URL |
| --- | --- |
| Application | http://localhost:3000 |
| API (direct) | http://localhost:8000 (interactive docs at `/docs` outside production) |
| PostgreSQL | `localhost:5432` (bound to localhost only) |

Create the first administrator (section 9), then sign in at http://localhost:3000.

To load **fictional** demo users and companies for development:

```bash
docker compose exec backend python -m scripts.seed_dev --companies
```

| Demo user (fictional) | Role |
| --- | --- |
| demo.admin@example.com | Administrator |
| demo.manager@example.com | Sales Manager |
| demo.agent1@example.com | Salesperson |
| demo.agent2@example.com | Salesperson |

All demo users share the password `LeadFinder-Dev-2026!`. The seed script refuses to run when `ENVIRONMENT` is
`staging` or `production`. Demo companies have the source **Demo data**, so they are never mistaken for imported Odoo
records.

## 4. Importing Odoo data

Odoo is the source of truth for existing TECOMSA relationships. Until Odoo data is imported, every company shows
**Not checked**.

1. **Export from Odoo** (list view → select all → *Export*, as XLSX or CSV):
   - **CRM → Pipeline**: include archived and lost records. Useful fields: Opportunity, Customer, Contact Name,
     Email, Phone, Salesperson, Sales Team, Stage, Type, Expected Revenue, Probability, Active, Lost Reason,
     Created on, Last Updated on. Include the **ID** field so re-imports update records instead of duplicating them.
   - **Contacts**: include companies and individuals. LeadFinder reads Company Name, Contact Name, Job Position,
     Phone / Mobile (mobile preferred), Email, Country and City. It also uses ID and Is a Company when present.
2. In LeadFinder, go to **Data sources → Odoo imports** and choose the file. It is uploaded immediately.
3. Columns are **detected automatically** from the headers (case, spaces, underscores and hyphens are ignored, so
   `Company Name`, `company_name` and `COMPANY NAME` are the same). There is no mapping step. A file with no
   Company Name or Contact Name column is rejected with a message listing the columns that were found.
4. Check the **preview**: rows detected, ready, duplicates, warnings, and the rows as LeadFinder will save them.
   A person is never turned into a company: `Mohammad Hassan / General Manager` at `ABC Foods SAL` is stored as a
   contact of that company (shown in its Contacts tab), and the row's phone and email fill the company's phone and
   email when those are empty. A contact without a company is kept without one; a row with neither is skipped.
   A contacts import never creates CRM leads or opportunities: those companies are marked *Existing Odoo contact*.
   A contacts list uploaded as a CRM file is rejected (a CRM file needs an Opportunity / Lead name column).
5. Click **Import records.** Every company's relationship status is recalculated.
6. To undo, use the delete icon in the imports list:
   - **Delete import only** removes the history entry and stored file and keeps the records.
   - **Delete import and imported data** also removes the records and companies that came only from that import.
     Companies used in a campaign or with contacts or notes are kept, and so is anything a later import also
     contains.

To try it without real data, use the fictional files in `samples/`. Regenerate them with
`python -m scripts.sample_odoo_files` from `backend/`.

Relationship statuses, in order of precedence:

| Status | Meaning |
| --- | --- |
| Customer | A won opportunity (stage contains "Won" or probability 100%), or an Odoo contact flagged as a customer |
| Open opportunity / Open lead | An active, not lost, not won CRM record |
| Lost opportunity | Lost or archived CRM record |
| Odoo contact | Exists in Odoo contacts, with no CRM record |
| Available | Odoo data exists and nothing in it matches this company |
| Not checked | No Odoo import has completed yet |

Every status except *Available* and *Not checked* is **protected**. The company profile shows the reason, the owning
salesperson, the matching CRM records and the matching Odoo contacts.

## 5. Finding new companies (Phase 1)

1. Open **Find companies**, choose the country (Lebanon), an industry (or *Other / custom* to type one, e.g.
   "Plastic packaging manufacturer"), a city or governorate (or all of Lebanon) and how many new companies you want.
2. Click **Find companies.** The search runs in the background; the page shows each stage as the backend reports it
   (downloading/using the Overture data, matches found, companies examined, new / known / protected / duplicates).
3. Every candidate is normalised and checked, in this order: duplicate within the search → same source record
   already linked to a company → deterministic match against LeadFinder companies (website domain, phone, email
   domain, name + city, name) → TECOMSA's Odoo contacts and CRM records. Only companies with no match are saved,
   with their source and source id. Nothing is ever created in the CRM.
4. The results open on **New**; the other tabs show companies already in LeadFinder, those protected by Odoo
   (with the reason) and duplicates. Searches stay in **Search history**; running the same search again adds nothing
   twice. Admins can delete a search, optionally with the companies only it added.

Sources and access (no accounts, no keys, no paid services):

- **Overture Maps Places**: the latest release is found in the STAC catalog, only the GeoParquet file(s) covering
  the country are read over HTTPS with DuckDB, filtered by bounding box and country code. The Lebanon extract
  (~50,000 places, ~3 MB) is cached per release in `DISCOVERY_CACHE_DIR`; the first search of a release takes about
  a minute, later searches about a second.
- **OpenStreetMap** (Overpass API): one query per country, cached for 24 h. If Overpass is busy the search still
  completes from Overture and is marked *Partially completed*.

Industries are mapped to source categories and name keywords in
`backend/app/services/discovery/industries.py`; cities and governorates in `geography.py`. Place data ©
Overture Maps Foundation and contributors (CDLA Permissive 2.0 and other open licences) and © OpenStreetMap
contributors (ODbL).

## 6. Environment variables

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Required | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | yes | `development`, `test`, `staging` or `production` |
| `APP_SECRET` | prod | Reserved for app-level encryption/signing (≥32 random chars in production) |
| `JWT_SECRET` | prod | Signs session tokens (≥32 random chars in production) |
| `FRONTEND_URL` | yes | Public frontend URL, used for CORS |
| `SESSION_EXPIRE_MINUTES` | no | Session lifetime (default 480) |
| `COOKIE_SECURE` | prod | `true` in production (HTTPS-only cookie) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | yes | Database credentials used by Docker Compose |
| `DATABASE_URL` | local | Backend DB URL when running **outside** Docker |
| `TEST_DATABASE_URL` | tests | Separate test DB; its name must end in `_test` |
| `MANAGERS_CAN_IMPORT` | no | `true` lets Sales Managers run Odoo imports (default: Admins only) |
| `IMPORT_STORAGE_DIR` | no | Where uploaded source files are kept (default `storage/imports`) |
| `IMPORT_MAX_BYTES` / `IMPORT_MAX_ROWS` | no | Upload limits (default 20 MB / 50,000 rows) |
| `BACKEND_INTERNAL_URL` | local | Where Next.js proxies `/api/*` when running outside Docker |
| `BACKUP_RETENTION_DAYS` / `BACKUP_INTERVAL_SECONDS` | no | Scheduled backup settings (production compose) |
| `ODOO_BASE_URL`, `ODOO_DATABASE`, `ODOO_API_KEY`, `LUSHA_API_KEY`, `AI_API_KEY` | no | **Reserved.** Not used in Phase 0 |

Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. In development, empty
`APP_SECRET`/`JWT_SECRET` fall back to insecure development values. In staging and production the backend refuses to
start without strong values.

## 7. Running without Docker

Start PostgreSQL 16 yourself and create two databases, `leadfinder` and `leadfinder_test`. Then:

**Backend**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head               # reads DATABASE_URL from ../.env
uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm ci
npm run dev                        # http://localhost:3000, proxies /api to BACKEND_INTERNAL_URL
```

For a production-like frontend, run `npm run build`, copy `.next/static` into `.next/standalone/.next/static` and
`public/` into `.next/standalone/public`, then run `node .next/standalone/server.js`. The production Docker image
does exactly this.

## 8. Database migrations

Run these commands from `backend/` (or prefix them with `docker compose exec backend`).

```bash
alembic upgrade head                              # apply all migrations
alembic current                                   # show the applied revision
alembic history                                   # list revisions
alembic revision --autogenerate -m "add x to y"   # create a migration after changing models
alembic check                                     # verify models and migrations are in sync
alembic downgrade -1                              # roll back the last migration
```

Always review autogenerated migrations before committing them. Take a backup before running migrations in production
(see [docs/OPERATIONS.md](docs/OPERATIONS.md)).

## 9. Creating the initial administrator

```bash
docker compose exec backend python -m scripts.create_admin --email you@tecomsa.me --name "Your Name"
```

You will be prompted for the password (minimum 10 characters). For non-interactive provisioning, set
`LEADFINDER_ADMIN_PASSWORD` in the environment of that one command. After that, administrators create all other
accounts from **Administration → Users**. Self-registration does not exist.

## 10. Running tests

Tests use the separate `leadfinder_test` database. The development compose file creates it automatically the first
time the Postgres volume is initialised. Each test run migrates it from scratch (downgrade to base, then upgrade to
head), and tables are emptied between tests.

```bash
docker compose exec backend pytest
# or locally, from backend/:
TEST_DATABASE_URL=postgresql+psycopg://leadfinder:<pw>@localhost:5432/leadfinder_test pytest
```

The 71 tests cover:

- **Auth and access:** login, rejection, rate limiting, logout revocation, deactivation, role and record permissions,
  import and CRM permissions
- **Companies and campaigns:** company creation and normalisation (including Lebanese phone numbers and
  `ABC Foods SAL` / `S.A.L.` / `ABC FOODS`), campaigns and linking, audit and activity events
- **Odoo imports:** CRM and contact imports (XLSX and CSV), automatic header detection and variants, company/person
  split, preview without writes, in-file duplicates, idempotent re-imports, deleting imports with and without data
  (no orphans), invalid and corrupt files
- **Protection:** relationship statuses, protection of manually added duplicates, dashboard counts, company filters
- **Acceptance:** the full Phase 0 acceptance scenarios

Frontend: `cd frontend && npm run typecheck && npm run build`.

## 11. Roles

| Capability | Admin | Sales Manager | Salesperson |
| --- | :-: | :-: | :-: |
| Dashboard, companies (view all, add), relationship reasons | ✓ | ✓ | ✓ |
| Edit a company | all | all | only ones they created |
| Campaigns: view / edit | all | all | only their own |
| CRM records and sales team views | ✓ | ✓ | – |
| Odoo imports and import history | ✓ | if `MANAGERS_CAN_IMPORT=true` | – |
| Link salespeople to user accounts | ✓ | – | – |
| Users, audit log, integrations and settings | ✓ | – | – |

All rules are enforced by the backend. The frontend only hides what a role cannot use.

## 12. Current limitations

- Odoo data arrives only through CSV/XLSX imports. There is no Odoo API sync, and relationship status is only as
  current as the latest import.
- Matching is deterministic: Odoo ID, website domain, company email domain, phone and normalised name. Two different
  organisations with the same normalised name are treated as the same company.
- "Won" is inferred from a stage name containing "Won" or a probability of 100%, because Odoo exports have no explicit
  won flag.
- No Lusha, AI qualification, website research or decision-maker search. Lusha usage stays 0.
- Discovery is limited by what the free sources contain. Overture has no specific "food manufacturing" category for
  Lebanon, so industries are matched by category + name keywords: companies whose names say nothing about what they
  make can be missed. Many localities are in Arabic and are shown as the source gives them.
- Governorate boundaries are approximated with boxes; cities with a radius around the centre.
- Discovery runs in a background thread of the backend process; a run interrupted by a restart is marked failed or
  partially completed at the next start.
- Campaigns can only move between `DRAFT`, `READY` and `CANCELLED`.
- The login rate limiter is in-memory per backend process.

## 13. Phase 2 readiness

- **Discovered companies:** every discovered company has its website (when the source has one), category,
  location and source provenance (`company_sources`), ready for website research and AI qualification.
- **Protection layer:** `relationship_service` answers "does TECOMSA already know this company?" with a status, reason
  and owner. Discovery already calls it for every candidate; qualification should too.
- **Matching:** `matching_service` provides the signals and scores. A future Odoo API sync can write into the same
  `crm_leads` / `odoo_contacts` tables and reuse the same recalculation.
- **Sources:** a new discovery source is one provider class returning `Candidate`s
  (`backend/app/services/discovery/base.py`); normalisation, dedupe, protection and saving are shared.
- **Intelligence fields:** the company profile's Intelligence tab (Odoo fit, Frinzo fit, research, decision-makers,
  AI reasoning) is ready to populate.
- **Owners:** salespeople can be linked to LeadFinder users, which enables lead routing to the relationship owner.
