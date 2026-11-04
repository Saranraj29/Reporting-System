# Project Transparency Platform

Tasks, time, daily status, dashboards and client-ready reports in one multi-tenant web app — built from
*Project Transparency Platform – System Design v1*. **The AI drafts, a person approves.**

Three deployables, one codebase, one database:

| Piece | Tech | Where |
|---|---|---|
| Web app | React + TypeScript (Vite), MUI, Recharts | [`frontend/`](frontend) |
| API | Python 3.12, FastAPI, SQLAlchemy 2, Alembic | [`backend/app`](backend/app) |
| Worker | same image as the API: `python -m app.worker` | [`backend/app/worker.py`](backend/app/worker.py) |
| Database | PostgreSQL 16 — row-level security + the job queue | [`backend/alembic`](backend/alembic) |

## Screenshots

| | |
|---|---|
| ![Dashboard](docs/screenshots/02-dashboard.png) **Dashboard** | ![Tasks](docs/screenshots/03-tasks.png) **Tasks** |
| ![My day](docs/screenshots/13-my-day.png) **My day** — timer, time log, daily status | ![Report review](docs/screenshots/09-report-review.png) **AI-drafted client report review** |
| ![Shared page](docs/screenshots/11-shared-report.png) **Public client page** (no login, expires) | ![Roles](docs/screenshots/16-admin-roles.png) **Roles & permissions** (data, not code) |

All 19 screens: [`docs/screenshots`](docs/screenshots). They are produced by the E2E tour (`e2e/ui.cjs`).

## Run it

### Docker (recommended for a first run)
Needs Docker Desktop / Docker Engine with the Compose plugin. Nothing else (no Python, Node or PostgreSQL).
```bash
docker compose up --build -d                  # or: make up
docker compose --profile demo run --rm seed   # optional demo company, or: make seed
```
Open **http://localhost:8080** (API docs: http://localhost:8080/api/docs). Log in with the demo users below, or register a
new company with any work-domain email. There is no mail server in dev, so verification links appear on the sign-up
screen ("verify now") and every email is printed in the worker log: `docker compose logs -f worker` (`make logs`).

| Service | What it is | Port |
|---|---|---|
| `web` | nginx serving the built React app and proxying `/api` to the API | 8080 |
| `api` | FastAPI (healthchecked; `web` waits for it) | internal |
| `worker` | same image, `python -m app.worker` | internal |
| `migrate` | one-shot `alembic upgrade head`, runs before api/worker | – |
| `db` | PostgreSQL 16, roles created by `infra/db/init.sql` | 127.0.0.1:5433 |

Useful: `make down` (stop, keep data) · `make reset` (stop and wipe database + report files) ·
`WEB_PORT=9090 docker compose up -d` if 8080 is taken · put `ANTHROPIC_API_KEY=...` in a root `.env` file to get real AI
drafts instead of figures-only drafts (copy `.env.example`; Compose reads it automatically).
The first build is slow (~5 min) because the backend image bundles Chromium for PDF export.

### Local development
```bash
# 1. PostgreSQL 16 with the two roles (owner for migrations, non-owner for the app so RLS applies)
psql -U postgres -f infra/db/init.sql

# 2. API + worker
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt && playwright install chromium
export MIGRATION_DATABASE_URL=postgresql+psycopg://rs_owner:rs_owner@localhost:5432/reporting
alembic upgrade head && python -m app.seed
uvicorn app.main:app --reload            # :8000
python -m app.worker                     # second terminal

# 3. Web
cd frontend && npm install && npm run dev   # :5173, proxies /api to :8000
```
Demo logins (password `Demo@12345`): `priya@northwind.dev` Manager · `asha@northwind.dev` Company Admin ·
`karthik@northwind.dev` Team Lead · `divya@northwind.dev` Team Member · `rohan@northwind.dev` CEO/CTO.

Configuration is environment variables — see [`.env.example`](.env.example). With no `ANTHROPIC_API_KEY` the
drafting step produces a deterministic **figures-only** draft, so the whole flow works offline.

## Tests and CI

```bash
cd backend  && pytest          # 99 tests, need PostgreSQL (TEST_PG_ADMIN_DSN, default postgres:postgres@localhost)
cd frontend && npm test        # 15 unit tests;  npm run typecheck;  npm run build
cd e2e && node ui.cjs          # browser tour against the running stack (+ screenshots)
```
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push: **backend** (ruff + pytest on a
PostgreSQL 16 service, including PDF rendering), **frontend** (typecheck, vitest, build), **e2e** (boots API, worker
and web app, runs the Playwright tour, uploads screenshots) and **docker** (builds both images).

What the backend tests prove: tenant isolation *in the database* (a query without a filter sees only its own company,
cross-tenant writes are rejected), permission scopes (own / team / all) on tasks, reports, dashboard and status,
registration rules (domain join / create / invite / public-domain block), password reset single use, refresh-token
revocation, custom task fields, the timer (one running timer per user), derived hours, report figures and exports
(xlsx/docx/pdf), the client-report workflow (draft → edit → redraft → approve → share → public page, expiry, revoke),
the AI privacy boundary (prompt contains only aggregated client figures), job retries (3 attempts then failed), Slack/email
partial-failure retry, and schedule timing per company timezone.

## How the design maps to the code

* **Tenancy** – `company_id` on every business table; PostgreSQL RLS policies on `current_setting('app.company_id')`,
  set per transaction from the signed JWT. The app role does not own the tables. Login, domain check, share-token lookup
  and the worker's company scan use four narrow `SECURITY DEFINER` functions. ([`0001_initial.sql`](backend/alembic/versions/0001_initial.sql))
* **Roles & permissions** – ~26 `area.action.scope` keys in code, roles are rows. `require("task.view")` resolves the
  highest scope the user holds; `own`/`team`/`all` become query filters ([`perms.py`](backend/app/perms.py), [`deps.py`](backend/app/deps.py)).
* **Configurable by data** – roles, task fields (built-ins can be hidden, never dropped), report templates, schedules, Slack link.
* **Reports are plug-ins** – one module per report in [`reports/`](backend/app/reports) (`weekly`, `monthly`, `performance`);
  exporters and the AI step only see the `figures` JSON.
* **Worker** – reminders (17:30 status, 09:00 due/overdue), blocker alerts, report export, AI drafting, scheduled
  templates (Fri 16:00 / 1st), scheduled report email (Mon 07:00 / 1st), share emails; all in company time.
* **AI** – `draft_report_text(figures, template)` ([`services/ai.py`](backend/app/services/ai.py)); one prompt, one call,
  figures sanitised, JSON out; provider swap = `_call_model`.

## Deliberate differences from the design document

These are the places where the code does something other than (or beyond) the written design:

| Design | Implemented | Why |
|---|---|---|
| Procrastinate for jobs | Small `jobs` table + `SELECT … FOR UPDATE SKIP LOCKED`, retries with backoff, dedupe keys | Same property (queue in PostgreSQL), no extra dependency; Procrastinate can replace it behind `services/jobs.py` |
| passlib + bcrypt | `bcrypt` directly (cost 12) | passlib is unmaintained and breaks with bcrypt ≥ 4 |
| Rotating refresh token | Stateless refresh JWT carrying a per-user version; `logout`, password reset and deactivation bump it (revokes all sessions) | The 21-table model has no token table; per-token rotation needs one |
| ~20 permission keys | 26 (adds `dashboard.view.own` so members get a personal dashboard) | Team Members need *some* dashboard key |
| 21 tables | 23: adds `client_contacts` (report recipients) and `jobs`; extra columns `tasks.completed_at`, `report_runs.{report_key,params,scope_user_ids,export_format,…}`, `report_shares.{revoked_at,emailed_at}`, `notification_log.{status,error}` | Needed by the flows described |
| `report_runs.status` queued/drafted/approved/sent/failed | adds `ready` for plain exports | "marks the run done" needs a state |
| S3 file storage | local-disk `Storage` (put/get) | An S3 backend only has to implement those two functions — not written |
| Company Admin: “users, roles, projects, settings” | also gets task/dashboard/status views and weekly/monthly reports (never performance, approve or share) | The table says "no performance reports unless given that key" |

## Not verified here

* The Docker CI job has not run on GitHub yet. The compose stack itself *was* run end to end in the build sandbox (migrate,
  seed, healthchecks, login, PDF export, and the full browser tour against http://localhost:8080), but with two
  sandbox-only workarounds that do not touch the repo's files: the sandbox proxy's CA certificate was injected and
  Chromium was copied in, because the sandbox could not download Playwright's browser. On a normal machine
  `docker compose up --build` fetches it itself — that exact download step was the one part not exercised.
* The real Anthropic call (`_call_model`) and Google sign-in verification — exercised only with fakes; no keys were available.
* SMTP/SES delivery and a real Slack webhook — mail/Slack calls are faked in tests; the console mail backend is used in dev.
* Performance targets (dashboard < 1 s at 20k tasks, export < 30 s) — not load-tested.
