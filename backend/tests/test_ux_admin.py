"""Profile + preferences, teams as departments with team tasks, search filters, default role without the AI assistant."""

import datetime as dt

from .conftest import add_user, drain, login


# ------------------------------------------------------------------ profile and preferences
def test_profile_and_preferences(org):
    me = org.m1.get("/me").json()
    assert me["profile"]["phone"] == "" and me["prefs"] == {"email_reminders": True, "start_page": "/", "compact_tables": False}
    r = org.m1.patch("/me/profile", {"phone": " +91 98765 43210 ", "job_title": "QA engineer", "location": "Chennai", "bio": "Loves tests.", "name": "Mia M."})
    assert r.status_code == 200 and r.json()["phone"] == "+91 98765 43210" and r.json()["name"] == "Mia M."
    me = org.m1.get("/me").json()
    assert me["name"] == "Mia M." and me["profile"]["job_title"] == "QA engineer" and me["profile"]["email"] == "mia.member@acme.com"
    assert org.m1.patch("/me/profile", {"email": "x@y.com"}).json()["email"] == "mia.member@acme.com"  # the e-mail is not editable here
    assert org.m1.patch("/me/profile", {"name": ""}).status_code == 422
    p = org.m1.put("/me/preferences", {"email_reminders": False, "start_page": "/tasks"}).json()
    assert p == {"email_reminders": False, "start_page": "/tasks", "compact_tables": False}
    assert org.m1.put("/me/preferences", {"start_page": "/admin/users"}).json()["code"] == "invalid_start_page"
    assert org.m1.get("/me").json()["prefs"]["start_page"] == "/tasks" and org.m2.get("/me").json()["prefs"]["start_page"] == "/"


def test_change_password(org, client):
    assert org.m1.post("/me/password", {"current_password": "wrong-password", "new_password": "N3w-passw0rd!"}).json()["code"] == "wrong_password"
    assert org.m1.post("/me/password", {"current_password": "Passw0rd!pass", "new_password": "short"}).status_code == 422
    assert org.m1.post("/me/password", {"current_password": "Passw0rd!pass", "new_password": "N3w-passw0rd!"}).status_code == 204
    assert client.post("/api/v1/auth/login", json={"email": "mia.member@acme.com", "password": "Passw0rd!pass"}).status_code == 401
    assert login(client, "mia.member@acme.com", "N3w-passw0rd!")


def test_reminder_emails_respect_the_preference(work, owner_conn):
    from app.services import mail
    from app.worker import schedule_tick

    work.m1.put("/me/preferences", {"email_reminders": False})
    owner_conn.execute("update companies set timezone = 'UTC'")
    now = dt.datetime.now(dt.UTC).replace(hour=11, minute=0)
    while now.weekday() >= 5:
        now -= dt.timedelta(days=1)
    mail.outbox.clear()
    schedule_tick(now)
    drain()
    recipients = {m["to"] for m in mail.outbox}
    assert "mia.member@acme.com" not in recipients and "max.member@acme.com" in recipients  # Mia muted hers, Max did not


# ------------------------------------------------------------------ default role
def test_new_people_get_team_member_without_the_ai_assistant(org):
    assert org.m1.get("/me").json()["roles"] == [{"id": org.m1.get("/me").json()["roles"][0]["id"], "name": "Team Member"}]
    assert "assistant.use" not in org.m1.get("/me").json()["permissions"]
    assert org.m1.get("/assistant/status").status_code == 403
    assert org.m1.post("/assistant/chat", {"quick_action": "my_due"}).status_code == 403
    for api in (org.lead, org.mgr, org.admin):  # other roles keep it
        assert "assistant.use" in api.get("/me").json()["permissions"]
    new = add_user(org.admin, "Nina New", "Team Member")
    assert "assistant.use" not in new.get("/me").json()["permissions"]


# ------------------------------------------------------------------ teams as departments + team tasks
def test_teams_have_a_description_and_tasks_belong_to_a_team(work):
    t = work.admin.post("/teams", {"name": "Design", "description": "UI and brand", "lead_user_id": work.lead.user_id}).json()
    assert t["description"] == "UI and brand" and t["open_tasks"] == 0
    task = work.mgr.post("/tasks", {"project_id": work.project["id"], "title": "Logo refresh", "team_id": t["id"], "assignee_ids": [work.m1.user_id]}).json()
    assert task["team_id"] == t["id"] and task["team_name"] == "Design"
    assert work.mgr.post("/tasks", {"project_id": work.project["id"], "title": "x", "team_id": "00000000-0000-0000-0000-000000000000"}).json()["code"] == "invalid_team"
    teams = {x["name"]: x for x in work.admin.get("/teams").json()["items"]}
    assert teams["Design"]["open_tasks"] == 1 and teams["Design"]["total_tasks"] == 1
    assert [x["title"] for x in work.mgr.get("/tasks", params={"team": t["id"]}).json()["items"]] == ["Logo refresh"]
    # change it later: an activity note records who moved it where
    t2 = work.admin.post("/teams", {"name": "QA"}).json()
    moved = work.mgr.patch(f"/tasks/{task['id']}", {"team_id": t2["id"]}).json()
    assert moved["team_name"] == "QA"
    notes = [c["body"] for c in work.mgr.get(f"/tasks/{task['id']}/comments").json()["items"] if c["kind"] == "system"]
    assert any("assigned this task to the team **QA**" in n for n in notes)
    assert work.mgr.patch(f"/tasks/{task['id']}", {"team_id": None}).json()["team_id"] is None
    patched = work.admin.patch(f"/teams/{t['id']}", {"description": "Product design"}).json()
    assert patched["description"] == "Product design"


# ------------------------------------------------------------------ search
def test_search_filters(work):
    a = work.admin
    assert [u["name"] for u in a.get("/users", params={"q": "maya"}).json()["items"]] == ["Maya Manager"]
    assert [u["name"] for u in a.get("/users", params={"q": "acme.com"}).json()["items"]][:1]  # e-mail matches too
    assert [r["name"] for r in a.get("/roles", params={"q": "lead"}).json()["items"]] == ["Team Lead"]
    assert [p["name"] for p in a.get("/projects", params={"q": "apol"}).json()["items"]] == ["Apollo"]
    assert [p["name"] for p in a.get("/projects", params={"q": "globex"}).json()["items"]] == ["Apollo"]  # by client name
    assert [c["name"] for c in a.get("/clients", params={"q": "gina"}).json()["items"]] == ["Globex"]
    assert [t["name"] for t in a.get("/teams", params={"q": "cor"}).json()["items"]] == ["Core"]
    assert a.get("/teams", params={"q": "zzz"}).json()["items"] == []
