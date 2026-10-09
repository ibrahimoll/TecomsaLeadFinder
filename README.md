# TECOMSA LeadFinder

Internal B2B sales-intelligence platform for TECOMSA (Frinzo, Odoo ERP and IT Solutions), starting with the
Lebanese market. A lead generator finds companies, opens one, picks the department they sell to (IT, Finance,
HR, …) and gets the right current person with the best available business contact, each with its evidence.

What it does:

- **Find Leads** — discovers companies LeadFinder does not have yet, by industry and area, from free public data
  (Overture Maps Places, OpenStreetMap, Wikidata, public directories). Known companies are counted, never re-offered.
- **Company search** — finds one company by name, Arabic / French / English variants, domain or phone.
- **Company research** — reads the company's own website (and permitted public sources) for facts, locations,
  products, signals and people, with the source of every fact.
- **People and contacts** — decision-makers by department with current / former status, published business
  emails and phones (classified: direct line, business mobile, WhatsApp, extension, company switchboard),
  email-pattern predictions clearly labelled as predictions, and evidence for each.
- **Proprietary contact network** — TECOMSA CRM exports, business cards, email signatures, meeting contacts and
  contacts added by hand; sales feedback (delivered / replied / bounced, phone right / wrong, person left) that
  confirms or invalidates contacts for the next salesperson. Internal contacts keep their owner and visibility.

No paid contact-data provider is used, and nothing is ever sent to a contact to test it.

| Document | Contents |
| --- | --- |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Deployment, database access, backups and restore, people sources, imports, benchmarks, troubleshooting |
| [SECURITY.md](SECURITY.md) | Security model and hardening |

---

## 1. Architecture

```
Browser ──► Next.js (frontend, :3000) ──/api/* proxy──► FastAPI (backend, :8000) ──► PostgreSQL 16
                                                              └── job worker (research, discovery, contacts)
```

- **Frontend:** Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Pydantic 2, Alembic; DuckDB for the map-data extracts
- **Database:** PostgreSQL 16 (pg_trgm); background jobs are a PostgreSQL queue (no Redis)
- **Auth:** email + password (Argon2id), server-side sessions, signed token in an httpOnly cookie

```
.
├── backend/
│   ├── app/
│   │   ├── api/          Routes and dependencies (auth, roles, pagination)
│   │   ├── core/         Settings, security, exceptions
│   │   ├── models/       ORM models (companies, people, emails, phones, evidence, sources, …)
│   │   ├── schemas/      Request / response models
│   │   └── services/     discovery/ (Find Leads), enrichment/ (company research), people/ (people research,
│   │                     public people sources), contact_intelligence, contributions, contact_feedback, jobs
│   ├── migrations/       Alembic migrations
│   ├── scripts/          create_admin, seed_dev, benchmarks (contact_coverage, people_coverage, search_*,
│   │                     source_inventory), lebanon_sources
│   ├── benchmarks/       Fixed benchmark sets and their latest results
│   └── tests/            pytest suite (separate test database)
├── frontend/
│   ├── app/              Pages (companies, find-leads, admin, settings)
│   ├── components/       App shell, design-system primitives (components/ui), feature components
│   ├── lib/              API client, constants, formatting
│   └── types/            Shared TypeScript types
├── docker/postgres/init/ Dev-only DB init (creates the test database)
├── scripts/              Database backup / restore scripts
├── docker-compose.yml        Development stack
├── docker-compose.prod.yml   Production stack (+ scheduled backups)
└── .env.example              Environment template
```

## 2. Requirements

- Docker Desktop (or Docker Engine) with Docker Compose v2, **or**
- Without Docker: Python 3.12+, Node.js 20+ (22 LTS recommended), PostgreSQL 16

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

Create the first administrator (section 7), then sign in. For **fictional** demo users and companies in
development: `docker compose exec backend python -m scripts.seed_dev --companies` (all demo users share the password
`LeadFinder-Dev-2026!`; the script refuses to run in staging or production).

## 4. Environment variables

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Required | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | yes | `development`, `test`, `staging` or `production` |
| `APP_SECRET` / `JWT_SECRET` | prod | ≥32 random characters in production (sessions are signed with `JWT_SECRET`) |
| `FRONTEND_URL` | yes | Public frontend URL, used for CORS |
| `SESSION_EXPIRE_MINUTES` | no | Session lifetime (default 480) |
| `COOKIE_SECURE` | prod | `true` in production (HTTPS-only cookie) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | yes | Database credentials used by Docker Compose |
| `APP_DB_USER` / `APP_DB_PASSWORD` | prod | The application's own non-superuser role (production compose) |
| `DATABASE_URL` | local | Backend DB URL when running **outside** Docker |
| `TEST_DATABASE_URL` | tests | Separate test DB; its name must end in `_test` |
| `DISCOVERY_CACHE_DIR` | no | Where map-data extracts are cached (default `storage/discovery`) |
| `BACKEND_INTERNAL_URL` | local | Where Next.js proxies `/api/*` when running outside Docker |
| `BACKUP_RETENTION_DAYS` / `BACKUP_INTERVAL_SECONDS` | no | Scheduled backup settings (production compose) |

Every other setting has a safe default in `backend/app/core/config.py` (research time limits, Common Crawl budget,
`EMAIL_SMTP_VERIFICATION` — off by default). Generate secrets with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`. In staging and production the backend refuses to start
without strong secrets.

## 5. Running without Docker

Start PostgreSQL 16 yourself and create two databases, `leadfinder` and `leadfinder_test`. Then:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head               # reads DATABASE_URL from ../.env
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
npm ci
npm run dev                        # http://localhost:3000, proxies /api to BACKEND_INTERNAL_URL
```

## 6. Database migrations

From `backend/` (or prefixed with `docker compose exec backend`):

```bash
alembic upgrade head                              # apply all migrations
alembic current                                   # show the applied revision
alembic revision --autogenerate -m "add x to y"   # create a migration after changing models
alembic check                                     # verify models and migrations are in sync
alembic downgrade -1                              # roll back the last migration
```

Review autogenerated migrations before committing them, and back up before migrating production
(see [docs/OPERATIONS.md](docs/OPERATIONS.md)).

## 7. Creating the initial administrator

```bash
docker compose exec backend python -m scripts.create_admin --email you@tecomsa.me --name "Your Name"
```

You are prompted for the password (minimum 10 characters); for non-interactive provisioning set
`LEADFINDER_ADMIN_PASSWORD` for that one command. Administrators create all other accounts under
**Administration → Users**. There is no self-registration.

## 8. Running tests

Tests use the separate `leadfinder_test` database, rebuilt from the migrations at the start of each run and emptied
between tests. Run one test session at a time: two sessions on the same test database interfere.

```bash
docker compose exec backend pytest
cd frontend && npm run typecheck && npm run build
```

## 9. Roles

| Capability | Admin | Sales Manager | Salesperson |
| --- | :-: | :-: | :-: |
| Companies, people and contacts (view, add, research, correct, give feedback) | ✓ | ✓ | ✓ |
| Delete a company; remove a person on request (privacy) | ✓ | ✓ | – |
| Find Leads searches | all | all | their own |
| TECOMSA / contributed contacts marked *managers* | ✓ | ✓ | only their own |
| TECOMSA / contributed contacts marked *private* | owner only | owner only | owner only |
| See the user list | ✓ | ✓ | – |
| Create / edit users, audit log, system status | ✓ | – | – |

All rules are enforced by the backend; the frontend only hides what a role cannot use.

Place data © Overture Maps Foundation and contributors (CDLA Permissive 2.0 and other open licences) and
© OpenStreetMap contributors (ODbL).
