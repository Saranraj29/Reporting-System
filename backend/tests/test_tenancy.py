"""Tenant isolation is enforced by PostgreSQL itself, not only by application filters."""

import psycopg
import pytest

from .conftest import add_user, host, signup_admin


def _app_conn():
    return psycopg.connect(f"postgresql://rs_app:rs_app@{host}/rs_test", autocommit=False)


def _seed_two_companies(client):
    a = signup_admin(client, "acme.com", "Acme")
    b = signup_admin(client, "globex.com", "Globex")
    pa = a.post("/projects", {"name": "A-Project"}).json()
    pb = b.post("/projects", {"name": "B-Project"}).json()
    return a, b, pa, pb


def test_query_without_tenant_context_returns_nothing(client):
    _seed_two_companies(client)
    with _app_conn() as c:
        for table in ("projects", "users", "roles", "companies", "task_field_definitions"):
            assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table


def test_a_query_that_forgets_the_filter_only_sees_its_own_company(client):
    a, b, pa, pb = _seed_two_companies(client)
    me = a.get("/me").json()["company"]["id"]
    with _app_conn() as c:
        c.execute("SELECT set_config('app.company_id', %s, true)", (me,))
        names = [r[0] for r in c.execute("SELECT name FROM projects")]  # no WHERE clause on purpose
        assert names == ["A-Project"]
        assert c.execute("SELECT count(*) FROM companies").fetchone()[0] == 1


def test_cannot_write_rows_for_another_company(client):
    a, b, pa, pb = _seed_two_companies(client)
    ca = a.get("/me").json()["company"]["id"]
    cb = b.get("/me").json()["company"]["id"]
    with _app_conn() as c:
        c.execute("SELECT set_config('app.company_id', %s, true)", (ca,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO projects (company_id, name) VALUES (%s, 'sneaky')", (cb,))


def test_views_respect_row_level_security(client):
    a, b, *_ = _seed_two_companies(client)
    with _app_conn() as c:
        assert c.execute("SELECT count(*) FROM task_hours").fetchone()[0] == 0


def test_api_never_leaks_across_companies(client):
    a, b, pa, pb = _seed_two_companies(client)
    ta = a.post("/tasks", {"project_id": pa["id"], "title": "secret A task"}).json()
    assert b.get(f"/tasks/{ta['id']}").status_code == 404  # company B asking for A's id
    assert b.get("/tasks").json()["total"] == 0
    assert [p["name"] for p in b.get("/projects").json()["items"]] == ["B-Project"]
    # B cannot create a task in A's project
    assert b.post("/tasks", {"project_id": pa["id"], "title": "x"}).status_code == 400
    # nor see A's users
    assert {u["email"] for u in b.get("/users").json()["items"]} == {"admin@globex.com"}


def test_same_person_cannot_exist_in_two_companies(client):
    admin = signup_admin(client)
    signup_admin(client, "globex.com", "Globex")
    r = admin.post("/users", {"email": "admin@globex.com", "name": "Dup", "password": "Passw0rd!pass"})
    assert r.status_code == 409


def test_company_id_in_body_is_ignored(client):
    a, b, pa, pb = _seed_two_companies(client)
    cb = b.get("/me").json()["company"]["id"]
    r = a.post("/projects", {"name": "Injected", "company_id": cb})
    assert r.status_code == 201
    assert "Injected" not in [p["name"] for p in b.get("/projects").json()["items"]]


def test_slack_webhook_is_encrypted_at_rest(client, owner_conn):
    admin = signup_admin(client)
    url = "https://hooks.slack.com/services/T000/B000/SECRETSECRET"
    r = admin.patch("/settings", {"slack_webhook_url": url})
    assert r.status_code == 200 and r.json()["slack_configured"] and url not in str(r.json())
    stored = owner_conn.execute("SELECT slack_webhook_url FROM companies").fetchone()[0]
    assert stored and "SECRETSECRET" not in stored
    from app.security import decrypt

    assert decrypt(stored) == url


def test_domain_change_rules(client):
    admin = signup_admin(client)
    add_user(admin, "Zed Zee", "Team Member")
    assert admin.patch("/settings", {"email_domain": "gmail.com"}).status_code == 400
    assert admin.patch("/settings", {"email_domain": "other.com"}).status_code == 400  # admin's own email is not on it
    assert admin.patch("/settings", {"timezone": "Mars/Base"}).status_code == 400
    assert admin.patch("/settings", {"timezone": "Asia/Kolkata"}).json()["timezone"] == "Asia/Kolkata"
