# TECOMSA LeadFinder AI

Internal B2B prospecting platform for TECOMSA's three divisions: **Frinzo**, **Odoo ERP** and **IT Solutions**.

**Current state: Phase 0 (foundation).** This version has authentication, users and roles, a master company
database, contacts, campaign drafts, permissions and a full audit trail. It does **not** connect to Odoo, Lusha or any
AI provider yet, and it never shows simulated results from them.

| Document | Contents |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture, database schema, authentication, API, integration design |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Production deployment, database access, backups and restore, troubleshooting |

---

## 1. Technical architecture

```
Browser ──► Next.js (frontend, :3000) ──/api/* proxy──► FastAPI (backend, :8000) ──► PostgreSQL 16
```

- **Frontend:** Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Pydantic 2, Alembic
- **Database:** PostgreSQL 16
- **Auth:** email + password (Argon2id hashes), server-side sessions, signed token in an httpOnly cookie
- **Runtime:** Docker Compose (development and production files)

The browser only ever talks to the Next.js server. The server forwards `/api/*` to FastAPI, so the session cookie is
same-origin and the backend is never exposed directly.

```
.
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app factory, error handling, CORS
│   │   ├── api/               Routes and dependencies (auth, role checks, pagination)
│   │   ├── core/              Settings, security, rate limiting, domain exceptions
│   │   ├── db/                SQLAlchemy base and session
│   │   ├── models/            ORM models (one file per aggregate)
│   │   ├── schemas/           Pydantic request/response models
│   │   ├── services/          Business logic and permission rules
│   │   └── integrations/      odoo/ and lusha/ (disconnected interfaces)
│   ├── migrations/            Alembic migrations
│   ├── scripts/               create_admin.py, seed_dev.py
│   └── tests/                 pytest suite (separate test database)
├── frontend/
│   ├── app/                   Pages (login, dashboard, campaigns, companies, activity, admin)
│   ├── components/            UI primitives, forms, app shell
│   ├── lib/                   API client, constants, formatting
│   └── types/                 Shared TypeScript types
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
# Edit .env: at least set POSTGRES_PASSWORD (and matching password in DATABASE_URL / TEST_DATABASE_URL)

docker compose up --build
```

On startup the backend runs `alembic upgrade head`. Then:

| Service | URL |
| --- | --- |
| Application | http://localhost:3000 |
| API (direct) | http://localhost:8000 (interactive docs at `/docs` outside production) |
| PostgreSQL | `localhost:5432` (bound to localhost only) |

Create the first user (see section 7), then sign in at http://localhost:3000.

To load **fictional** demo users and companies for development:

```bash
docker compose exec backend python -m scripts.seed_dev --companies
```

| Demo user (fictional) | Role |
| --- | --- |
| demo.admin@example.com | Administrator |
| demo.manager@example.com | Sales Manager |
| demo.agent1@example.com | Sales Agent |
| demo.agent2@example.com | Sales Agent |

All demo users share the password `LeadFinder-Dev-2026!`. The seed script refuses to run when
`ENVIRONMENT` is `staging` or `production`. Demo companies are labelled "FICTIONAL development seed record".

## 4. Environment variables

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
| `BACKEND_INTERNAL_URL` | local | Where Next.js proxies `/api/*` when running outside Docker |
| `BACKUP_RETENTION_DAYS` / `BACKUP_INTERVAL_SECONDS` | no | Scheduled backup settings (production compose) |
| `ODOO_BASE_URL`, `ODOO_DATABASE`, `ODOO_API_KEY`, `LUSHA_API_KEY`, `AI_API_KEY` | no | **Reserved.** Not used in Phase 0 |

Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
In development, empty `APP_SECRET`/`JWT_SECRET` fall back to insecure development values. In staging and production
the backend refuses to start without strong values.

## 5. Running without Docker

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

## 6. Database migrations

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

## 7. Creating the initial administrator

```bash
docker compose exec backend python -m scripts.create_admin --email you@tecomsa.me --name "Your Name"
```

You will be prompted for the password (minimum 10 characters). For non-interactive provisioning, set
`LEADFINDER_ADMIN_PASSWORD` in the environment of that one command. After that, administrators create all other
accounts from **Administration → Users**. Self-registration does not exist.

## 8. Running tests

Tests use the separate `leadfinder_test` database. The development compose file creates it automatically the first
time the Postgres volume is initialised. Each test run migrates it from scratch, and tables are emptied between tests.

```bash
docker compose exec backend pytest
# or locally, from backend/:
TEST_DATABASE_URL=postgresql+psycopg://leadfinder:<pw>@localhost:5432/leadfinder_test pytest
```

The suite covers login, invalid-login rejection, rate limiting, logout revocation, admin user creation, role
enforcement (agents blocked from admin routes), company creation and normalisation, campaign creation, linking
companies to campaigns, record-level edit restrictions, audit events, the `NOT_CHECKED` Odoo default, zero Lusha usage,
disconnected integrations, and the full Phase 0 acceptance workflow.

Frontend type check: `cd frontend && npm run typecheck`.

## 9. Roles

| Capability | Admin | Sales Manager | Sales Agent |
| --- | :-: | :-: | :-: |
| Dashboard, companies (view all, add) | ✓ | ✓ | ✓ |
| Edit a company | all | all | only ones they created |
| Campaigns: view / edit | all | all | only their own |
| Create campaign drafts, add contacts | ✓ | ✓ | ✓ |
| Team activity | ✓ | ✓ | own only |
| List users | ✓ | ✓ (read-only, API) | – |
| Create, edit, activate or deactivate users | ✓ | – | – |
| Audit log and application settings | ✓ | – | – |

All rules are enforced by the backend. The frontend hides actions only for convenience.

## 10. Phase 0 limitations

- There is no Odoo connection. Every company shows **CRM status: Not checked**.
- There is no Lusha connection. Lusha credit usage is always **0**. The campaign budget field is stored but not used.
- There is no AI, lead scoring, company discovery, enrichment, email/WhatsApp sending or CRM sync.
- Campaigns can only move between `DRAFT`, `READY` and `CANCELLED`. `RUNNING`, `COMPLETED` and `FAILED` are reserved
  for the future pipeline.
- Companies and contacts are entered manually. No duplicate detection exists yet, but names, domains and phone numbers
  are normalised to support it later.
- There is no team or territory model. Managers see all campaigns, and agents see their own.
- The login rate limiter is in-memory per backend process.

## 11. Next: Phase 1

- **Odoo CRM verification:** implement `backend/app/integrations/odoo/` (`check_company`, `find_contact`,
  `find_opportunity`). Each check appends a row to `odoo_matches`.
- **Company duplicate detection:** built on `normalized_name`, `domain` and `main_phone_normalized`.
- Link LeadFinder users to Odoo users via `users.odoo_user_id`.

Later phases will add Lusha enrichment, recorded in `lusha_usage` and limited by the campaign budget, AI research and
outreach, and ML on the activity history.
