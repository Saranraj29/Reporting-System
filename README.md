# Project Transparency Platform

Tasks, time, daily status, dashboards and AI-written project reports in one multi-tenant web app — built from
*Project Transparency Platform – System Design v1*. **You see the report's structure first; it is written only after you say OK.**

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
| ![My day](docs/screenshots/13-my-day.png) **My day** — timer, time log, daily status | ![Structure preview](docs/screenshots/09-ai-report-structure.png) **AI report — structure preview, then OK** |
| ![AI report](docs/screenshots/11-ai-report-visibility.png) **Finished AI report** (PDF / Word / Excel / Markdown) | ![Roles](docs/screenshots/16-admin-roles.png) **Roles & permissions** (data, not code) |

All screens: [`docs/screenshots`](docs/screenshots). They are produced by the E2E tour (`e2e/ui.cjs`).

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

**Troubleshooting** — login shows `Unexpected token '<' … is not valid JSON` and the browser console says `502 (Bad Gateway)` on `/api/v1/…`:
nginx (the `web` container) cannot reach the `api` container.
```bash
docker compose ps                       # api must be "Up (healthy)"; migrate must be "Exited (0)"
docker compose logs --tail 50 api migrate
docker compose up --build -d            # recreates whatever is stale
```
If `api` is healthy but you still get 502 you are running an older web image that cached the API's address: `docker compose up --build -d`
(the current `nginx.conf` re-resolves `api` every 5 s, so this only happens once, on the old image).
Old data in a Docker volume is not the cause; `make reset` only if you want to start from an empty database.

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

### Choosing the LLM (Anthropic, OpenAI, Gemini) — environment only
Set any of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` (optionally `AI_PROVIDER`, `*_MODEL`, and `OPENAI_BASE_URL` for
Azure / vLLM / Ollama-style OpenAI-compatible servers) — see [`.env.example`](.env.example). `AI_PROVIDER=auto` (default) uses the first
provider that has a key, `none` forces figures-only drafts. **There is deliberately no UI or API for this in the current phase**: the
provider, model and keys are platform configuration. Every provider gets the same prompt with the same privacy boundary (aggregated
figures only). Adding another provider = one function in [`services/ai.py`](backend/app/services/ai.py).

## Tests and CI

```bash
cd backend  && pytest          # ~180 tests, need PostgreSQL (TEST_PG_ADMIN_DSN, default postgres:postgres@localhost)
cd frontend && npm test        # 15 unit tests;  npm run typecheck;  npm run build
cd e2e && node ui.cjs          # browser tour against the running stack (+ screenshots); needs a fresh seed and
                               # AUTH_RATE_LIMIT_PER_MIN=0 on the API (the tour logs in ~13 times from one IP)
```
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push: **backend** (ruff + pytest on a
PostgreSQL 16 service, including PDF rendering), **frontend** (typecheck, vitest, build), **e2e** (boots API, worker
and web app, runs the Playwright tour, uploads screenshots) and **docker** (builds both images).

What the backend tests prove: tenant isolation *in the database* (a query without a filter sees only its own company,
cross-tenant writes are rejected), permission scopes (own / team / all) on tasks, reports, dashboard and status,
registration rules (domain join / create / invite / public-domain block), password reset single use, refresh-token
revocation, custom task fields, the timer (one running timer per user), derived hours, report figures and exports
(xlsx/docx/pdf), the AI-report flow (request → structure preview → change → approve → files; owners limited to their projects; built-in fallback without an AI key),
the older client-template workflow (draft → edit → redraft → approve → share → public page; API only, no longer in the UI),
the AI privacy boundary (prompt contains only aggregated client figures), job retries (3 attempts then failed), Slack/email
partial-failure retry, and schedule timing per company timezone.

## How the design maps to the code

* **Tenancy** – `company_id` on every business table; PostgreSQL RLS policies on `current_setting('app.company_id')`,
  set per transaction from the signed JWT. The app role does not own the tables. Login, domain check, share-token lookup
  and the worker's company scan use four narrow `SECURITY DEFINER` functions. ([`0001_initial.sql`](backend/alembic/versions/0001_initial.sql))
* **Roles & permissions** – ~26 `area.action.scope` keys in code, roles are rows. `require("task.view")` resolves the
  highest scope the user holds; `own`/`team`/`all` become query filters ([`perms.py`](backend/app/perms.py), [`deps.py`](backend/app/deps.py)).
* **Task panel (GitLab-style issue view)** – status menu incl. **Testing**, sidebar with assignees / priority / due date / time tracking /
  timer, and an **Activity** feed: markdown comments (toolbar, preview), *internal notes* (author, leads, managers, admins and project owners
  only), and system notes written by the API ("changed status from … to …", "logged 2h", assignee/priority/due-date changes). *Close issue* /
  *Reopen issue* mark the task done / to do.
* **Daily check-ins** – two timestamped check-ins per person per day: the **morning plan** and the **end-of-day update** (editable until
  midnight, company timezone). Tracked everywhere: *My day* form, team **Check-ins** page (who posted, who is missing, blockers, log),
  dashboard cards, the weekly/monthly report (per-person completion rates + the log; internal reports only, never sent to a client or an LLM),
  and reminders (10:00 "share your plan", 17:30 "post your end-of-day update").
* **Project visibility report (the Markdown layout)** – a base report (`visibility`) per project: header table (period, project, owners, status),
  sprint goal + KPI row (planned / completed / in progress / pending / progress %), status pie, workflow, current activities, completed
  deliverables, work-distribution pie, and for several projects the *Combined Sprint Health*, *Summary Dashboard* and *Team Work Distribution*.
  All numbers are computed in code; as a client or internal **template** the AI only writes three sentences per project (sprint goal, workflow
  stages, key achievement) from figures without names, a person reviews/edits them, then approves. Download as **.md** (mermaid charts for GitHub/
  GitLab/VS Code), PDF, Word or Excel; the on-screen/PDF version draws the charts as SVG. Every other report can be downloaded as `.md` too.
  A real sample: [`docs/examples/project-visibility-report.md`](docs/examples/project-visibility-report.md) (figures-only fallback text, no AI key).
* **AI reports** (`/ai-reports`, for admins, the CTO/managers with `report.ai.draft`, and project owners for *their* projects only) – three simple steps:
  1. *Ask*: optional purpose ("update for the CTO, highlight delays"), projects (or *All projects*), people (or *Everyone*), period, and a format: **Default** (no format given — the AI
     proposes a clean industry-standard management report), **Project Visibility Report**, or **Own format** (paste the sections the employer asked for, a typed
     list like "1. Summary 2. Risks …", a full sample report, or upload a .md/.txt).
  2. *Structure preview*: a numbered list of sections with what each shows (table / chart / flow / written text) and which repeat per project.
     "Change something" re-plans it from a note; "Start over" discards it. **Nothing is written before the explicit OK.**
  3. *Report*: preview on screen plus PDF, Word, Excel and Markdown downloads; "Rewrite the text" keeps the structure and changes only the wording.
  How it is built ([`services/airep`](backend/app/services/airep)): **numbers, tables and charts come from code** (a catalog of 17 blocks computed from the
  project data); the AI only plans the outline (as JSON, validated against the catalog) and writes the text parts. People are replaced by
  codes before anything reaches the model and restored afterwards. Without an AI key, or if the provider fails on the last retry, built-in outlines and
  wording are used, so a report can always be produced. Limits: the format is reproduced *structurally* — unusual elements of a sample become written
  sections, not pixel-exact copies. Old client-share/approve endpoints remain in the API but are not used by the UI.
* **AI harness** ([`backend/app/ai`](backend/app/ai), from the *AI Hardening & Capability Plan*, Phase 0 step 1) – every model call for AI reports goes through
  `gateway.call_structured`: a JSON schema the provider must follow (forced tool use on Anthropic, strict `json_schema` on OpenAI, `responseSchema` on Gemini),
  temperature 0, validation in code, **one** repair call, then a built-in fallback in the same job attempt. `verify.py` checks every number, date, quoted task
  title and person code in the model's text against the facts it was given; a text that fails is replaced by built-in wording and counted ("N sections use
  standard wording"). `redact.py` turns people into codes and scrubs emails, phone numbers, @handles and links with query strings before anything is sent.
  Prompts are versioned files in `app/ai/prompts/` (`plan_v1.md`, `write_v1.md`); the model, prompt version, token usage, latency and verification result are stored on
  each report. Default OpenAI/Gemini model ids are pinned to dated versions.
* **Project owners** – a project can have owners (Admin → Projects & clients). An owner sees every task, comment, time entry and
  dashboard figure inside that project, whoever created it or is assigned to it (view only; editing still follows `task.edit.*`,
  and daily-status text is never widened). Company Admin, Manager and CEO/CTO hold `…view.all`, so they see every project.
* **Configurable by data** – roles, task fields (built-ins can be hidden, never dropped), report templates, schedules, Slack link.
* **Reports are plug-ins** – one module per report in [`reports/`](backend/app/reports) (`weekly`, `monthly`, `performance`);
  exporters and the AI step only see the `figures` JSON.
* **Worker** – reminders (17:30 status, 09:00 due/overdue), blocker alerts, report export, AI drafting, scheduled
  templates (Fri 16:00 / 1st), scheduled report email (Mon 07:00 / 1st), share emails; all in company time.
* **AI** – `draft_report_text(figures, template)` ([`services/ai.py`](backend/app/services/ai.py)); one prompt, one call,
  figures sanitised, JSON out; Anthropic / OpenAI / Gemini selected by environment variables (`resolve_config`).

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
* The real Anthropic, OpenAI and Gemini calls and Google sign-in verification — exercised only with fakes (request shapes are asserted
  in the tests, but no live key was available). Default model ids are pinned to dated versions (`gpt-4o-mini-2024-07-18`, `gemini-2.0-flash-001`) and change only after the golden set passes; they are settings.
* SMTP/SES delivery and a real Slack webhook — mail/Slack calls are faked in tests; the console mail backend is used in dev.
* Performance targets (dashboard < 1 s at 20k tasks, export < 30 s) — not load-tested.
