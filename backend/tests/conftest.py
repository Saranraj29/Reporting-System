import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import psycopg
import pytest

ADMIN_DSN = os.environ.get("TEST_PG_ADMIN_DSN", "postgresql://postgres:postgres@localhost:5432/postgres")
HOST_DSN = ADMIN_DSN.rsplit("/", 1)[0]  # postgresql://user:pass@host:port
DB = "rs_test"
BACKEND = Path(__file__).resolve().parent.parent
STORAGE = tempfile.mkdtemp(prefix="rs-files-")

host = HOST_DSN.split("@", 1)[1]
os.environ.update(
    APP_ENV="test",
    DATABASE_URL=f"postgresql+psycopg://rs_app:rs_app@{host}/{DB}",
    JWT_SECRET="test-secret-test-secret-test-secret-0123", PLATFORM_KEY="test-platform-key",
    EMAIL_BACKEND="console", STORAGE_DIR=STORAGE, AUTH_RATE_LIMIT_PER_MIN="0",
    ANTHROPIC_API_KEY="", GOOGLE_CLIENT_ID="test-client", JOB_BACKOFF_SECONDS="0",
    PUBLIC_WEB_URL="http://web.test", BCRYPT_ROUNDS="4",
)
if not os.environ.get("CHROMIUM_PATH") and Path("/opt/pw-browsers/chromium").is_file():
    os.environ["CHROMIUM_PATH"] = "/opt/pw-browsers/chromium"  # sandbox image; CI installs Playwright's own Chromium


def _owner() -> psycopg.Connection:
    return psycopg.connect(f"postgresql://rs_owner:rs_owner@{host}/{DB}", autocommit=True)


@pytest.fixture(scope="session", autouse=True)
def database():
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        for role, extra in (("rs_owner", "CREATEDB"), ("rs_app", "")):
            exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            if not exists:
                admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{role}' {extra}")
        admin.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {DB} OWNER rs_owner")
    with psycopg.connect(f"{HOST_DSN}/{DB}", autocommit=True) as c:
        c.execute("ALTER SCHEMA public OWNER TO rs_owner")
    env = {**os.environ, "MIGRATION_DATABASE_URL": f"postgresql+psycopg://rs_owner:rs_owner@{host}/{DB}", "APP_DB_ROLE": "rs_app"}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True)
    yield


@pytest.fixture(autouse=True)
def clean(database):
    from app.config import get_settings
    from app.db import reset_engine
    from app.security import reset_rate_limits
    from app.services import mail
    from app.services.access import clear_permission_cache
    from app.services.dashboard import clear_dashboard_cache

    get_settings.cache_clear()
    reset_engine()
    with _owner() as c:
        c.execute("TRUNCATE companies, jobs RESTART IDENTITY CASCADE")
    clear_permission_cache()
    clear_dashboard_cache()
    reset_rate_limits()
    mail.outbox.clear()
    yield


@pytest.fixture
def owner_conn():
    with _owner() as c:
        yield c


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


# ------------------------------------------------------------------ helpers
class Api:
    """Thin wrapper holding a bearer token."""

    def __init__(self, client, token: str, user_id: str | None = None):
        self.c, self.token, self.user_id = client, token, user_id

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, url, **kw):
        return self.c.get("/api/v1" + url, headers=self._h(), **kw)

    def post(self, url, json=None, **kw):
        return self.c.post("/api/v1" + url, headers=self._h(), json=json, **kw)

    def put(self, url, json=None, **kw):
        return self.c.put("/api/v1" + url, headers=self._h(), json=json, **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch("/api/v1" + url, headers=self._h(), json=json, **kw)

    def delete(self, url, **kw):
        return self.c.delete("/api/v1" + url, headers=self._h(), **kw)


PASSWORD = "Passw0rd!pass"


def signup_admin(client, domain: str = "acme.com", company: str = "Acme Corp", name: str = "Ada Admin") -> Api:
    """First user of a new domain becomes Company Admin."""
    email = f"admin@{domain}"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "name": name, "company_name": company})
    assert r.status_code == 201, r.text
    client.post("/api/v1/auth/verify-email", json={"token": r.json()["dev_verification_token"]}).raise_for_status()
    return login(client, email)


def login(client, email: str, password: str = PASSWORD) -> Api:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    api = Api(client, r.json()["access_token"])
    api.user_id = api.get("/me").json()["id"]
    return api


def role_id(admin: Api, name: str) -> str:
    return next(r["id"] for r in admin.get("/roles").json()["items"] if r["name"] == name)


def add_user(admin: Api, name: str, role: str, domain: str = "acme.com") -> Api:
    email = f"{name.lower().replace(' ', '.')}@{domain}"
    r = admin.post("/users", {"email": email, "name": name, "password": PASSWORD, "role_ids": [role_id(admin, role)]})
    assert r.status_code == 201, r.text
    return login(admin.c, email)


@pytest.fixture
def org(client):
    """Acme with an admin, manager, a team (lead + 2 members), an outsider and a project."""
    admin = signup_admin(client)
    mgr = add_user(admin, "Maya Manager", "Manager")
    lead = add_user(admin, "Leo Lead", "Team Lead")
    m1 = add_user(admin, "Mia Member", "Team Member")
    m2 = add_user(admin, "Max Member", "Team Member")
    out = add_user(admin, "Olive Outsider", "Team Member")
    team = admin.post("/teams", {"name": "Core", "lead_user_id": lead.user_id}).json()
    admin.put(f"/teams/{team['id']}/members", {"user_ids": [lead.user_id, m1.user_id, m2.user_id]}).raise_for_status()
    client_ = admin.post("/clients", {"name": "Globex", "contact_name": "Gina Globex", "contact_email": "gina@globex.com"}).json()
    project = admin.post("/projects", {"name": "Apollo", "client_id": client_["id"]}).json()
    return type("Org", (), dict(
        client=client, admin=admin, mgr=mgr, lead=lead, m1=m1, m2=m2, out=out, team=team, globex=client_, project=project,
    ))


def uid() -> str:
    return str(uuid.uuid4())


# ------------------------------------------------------------------ report data
def _seed_work(o, owner_conn):
    """Apollo (client Globex): T1 done 3h by Mia, T2 in progress 2h by Max, T4 overdue.  Hermes (no client): T3 blocked 1h by Mia.
    Olive (outside the team) has an Apollo task with 4h."""
    import datetime as dt

    hermes = o.admin.post("/projects", {"name": "Hermes"}).json()
    today = dt.date.today()

    def task(api, project, title, assignee, **kw):
        r = api.post("/tasks", {"project_id": project["id"], "title": title, "assignee_ids": [assignee.user_id], **kw})
        assert r.status_code == 201, r.text
        return r.json()

    t1 = task(o.mgr, o.project, "Ship login", o.m1, due_date=(today + dt.timedelta(days=1)).isoformat())
    t2 = task(o.mgr, o.project, "Build API", o.m2, due_date=(today + dt.timedelta(days=5)).isoformat())
    t3 = task(o.mgr, hermes, "Fix pipeline", o.m1)
    t4 = task(o.mgr, o.project, "Write docs", o.m1, due_date=(today - dt.timedelta(days=3)).isoformat())
    t5 = task(o.mgr, o.project, "Outside work", o.out)
    o.m1.patch(f"/tasks/{t1['id']}", {"status": "done"}).raise_for_status()
    o.m2.patch(f"/tasks/{t2['id']}", {"status": "in_progress"}).raise_for_status()
    o.m1.patch(f"/tasks/{t3['id']}", {"status": "blocked"}).raise_for_status()
    for api, t, h in ((o.m1, t1, 3), (o.m2, t2, 2), (o.m1, t3, 1), (o.out, t5, 4)):
        api.post("/time-entries", {"task_id": t["id"], "hours": h}).raise_for_status()
    o.hermes, o.tasks = hermes, dict(t1=t1, t2=t2, t3=t3, t4=t4, t5=t5)
    o.today = today
    return o


@pytest.fixture
def work(org, owner_conn):
    return _seed_work(org, owner_conn)


def drain():
    from app.worker import run_pending

    return run_pending()


def pdf_works() -> bool:
    try:
        from app.services.exporters import to_pdf

        return to_pdf("<p>x</p>").startswith(b"%PDF")
    except Exception:  # noqa: BLE001
        return False
