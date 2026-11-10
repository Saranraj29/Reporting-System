"""Profile + preferences, teams as departments with team tasks, search filters, default role without the AI assistant."""

from .conftest import add_user, login


# ------------------------------------------------------------------ profile and preferences
def test_profile_and_preferences(org):
    me = org.m1.get("/me").json()
    assert me["profile"]["phone"] == "" and me["prefs"] == {"start_page": "/", "compact_tables": False}
    r = org.m1.patch("/me/profile", {"phone": " +91 98765 43210 ", "job_title": "QA engineer", "location": "Chennai", "bio": "Loves tests.", "name": "Mia M."})
    assert r.status_code == 200 and r.json()["phone"] == "+91 98765 43210" and r.json()["name"] == "Mia M."
    me = org.m1.get("/me").json()
    assert me["name"] == "Mia M." and me["profile"]["job_title"] == "QA engineer" and me["profile"]["email"] == "mia.member@acme.com"
    assert org.m1.patch("/me/profile", {"email": "x@y.com"}).json()["email"] == "mia.member@acme.com"  # the e-mail is not editable here
    assert org.m1.patch("/me/profile", {"name": ""}).status_code == 422
    p = org.m1.put("/me/preferences", {"email_reminders": False, "start_page": "/tasks"}).json()  # reminders are a company/role setting now: the old key is ignored
    assert p == {"start_page": "/tasks", "compact_tables": False}
    assert org.m1.put("/me/preferences", {"start_page": "/admin/users"}).json()["code"] == "invalid_start_page"
    assert org.m1.get("/me").json()["prefs"]["start_page"] == "/tasks" and org.m2.get("/me").json()["prefs"]["start_page"] == "/"


def test_change_password(org, client):
    assert org.m1.post("/me/password", {"current_password": "wrong-password", "new_password": "N3w-passw0rd!"}).json()["code"] == "wrong_password"
    assert org.m1.post("/me/password", {"current_password": "Passw0rd!pass", "new_password": "short"}).status_code == 422
    assert org.m1.post("/me/password", {"current_password": "Passw0rd!pass", "new_password": "N3w-passw0rd!"}).status_code == 204
    assert client.post("/api/v1/auth/login", json={"email": "mia.member@acme.com", "password": "Passw0rd!pass"}).status_code == 401
    assert login(client, "mia.member@acme.com", "N3w-passw0rd!")


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


# ------------------------------------------------------------------ teams as departments: a team belongs to a PROJECT, its tasks inherit it
def test_a_team_belongs_to_a_project_and_its_tasks_inherit_it(work):
    t = work.admin.post("/teams", {"name": "Design", "description": "UI and brand", "lead_user_id": work.lead.user_id}).json()
    assert t["description"] == "UI and brand" and t["open_tasks"] == 0 and t["project_count"] == 0
    p = work.admin.patch(f"/projects/{work.project['id']}", {"team_id": t["id"]}).json()
    assert p["team_id"] == t["id"] and p["team_name"] == "Design"
    created = work.admin.post("/projects", {"name": "Brand site", "team_id": t["id"]}).json()
    assert created["team_name"] == "Design"
    assert work.admin.post("/projects", {"name": "Bad", "team_id": "00000000-0000-0000-0000-000000000000"}).json()["code"] == "invalid_team"
    # no team field on tasks any more: the task shows the team of its project
    assert work.mgr.post("/tasks", {"project_id": work.project["id"], "title": "Logo refresh", "assignee_ids": [work.m1.user_id]}).json()["team_name"] == "Design"
    tasks = work.mgr.get("/tasks", params={"team": t["id"]}).json()["items"]
    assert {x["project_name"] for x in tasks} == {"Apollo"} and "Logo refresh" in {x["title"] for x in tasks}
    assert work.mgr.get("/tasks", params={"team": work.admin.post("/teams", {"name": "QA"}).json()["id"]}).json()["items"] == []
    team = next(x for x in work.admin.get("/teams").json()["items"] if x["name"] == "Design")
    assert team["project_count"] == 2 and team["total_tasks"] == len(tasks) and team["open_tasks"] >= 1
    # filter projects by team, and search them by team name
    assert [x["name"] for x in work.admin.get("/projects", params={"team": t["id"]}).json()["items"]] == ["Apollo", "Brand site"]
    assert [x["name"] for x in work.admin.get("/projects", params={"q": "design"}).json()["items"]] == ["Apollo", "Brand site"]
    # clearing it
    assert work.admin.patch(f"/projects/{work.project['id']}", {"team_id": None}).json()["team_id"] is None


def test_team_filter_on_dashboard_and_reports(work):
    t = work.admin.post("/teams", {"name": "Design"}).json()
    work.admin.patch(f"/projects/{work.hermes['id']}", {"team_id": t["id"]})  # only Hermes belongs to Design
    full = work.admin.get("/dashboard").json()
    only = work.admin.get("/dashboard", params={"team": t["id"]}).json()
    assert only["total_hours"] == 1 and full["total_hours"] == 10  # Hermes logged 1h, everything else 9h
    rep = work.admin.get("/reports/visibility", params={"team": t["id"]}).json()["figures"]
    assert [p["name"] for p in rep["projects"]] == ["Hermes"]
    weekly = work.admin.get("/reports/weekly", params={"team": t["id"]}).json()["figures"]
    assert {p["project"] for p in weekly.get("by_project", [])} <= {"Hermes"}


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


# ------------------------------------------------------------------ project members join the project's team
def team_members(api, team_id):
    return set(next(t for t in api.get("/teams").json()["items"] if t["id"] == team_id)["member_ids"])


def test_people_added_to_a_project_join_its_team(org):
    team = org.admin.post("/teams", {"name": "Data"}).json()
    p = org.admin.post("/projects", {"name": "Pipeline", "team_id": team["id"]}).json()
    assert team_members(org.admin, team["id"]) == set()
    assert org.admin.put(f"/projects/{p['id']}/members", {"user_ids": [org.m1.user_id], "owner_ids": [org.lead.user_id]}).status_code == 200
    assert team_members(org.admin, team["id"]) == {org.m1.user_id, org.lead.user_id}  # members and owners both
    # adding again, or someone who is already in the team, does not duplicate or fail
    assert org.admin.put(f"/projects/{p['id']}/members", {"user_ids": [org.m1.user_id, org.m2.user_id]}).status_code == 200
    assert team_members(org.admin, team["id"]) == {org.m1.user_id, org.lead.user_id, org.m2.user_id}
    # taking someone off the project does not throw them out of the team (they may work on its other projects)
    org.admin.put(f"/projects/{p['id']}/members", {"user_ids": [org.m1.user_id]})
    assert org.m2.user_id in team_members(org.admin, team["id"])


def test_moving_a_project_to_a_team_brings_its_members_along(org):
    p = org.admin.post("/projects", {"name": "Site"}).json()  # no team yet
    org.admin.put(f"/projects/{p['id']}/members", {"user_ids": [org.m1.user_id, org.m2.user_id]})
    team = org.admin.post("/teams", {"name": "Web"}).json()
    assert team_members(org.admin, team["id"]) == set()  # a project without a team changes nothing
    org.admin.patch(f"/projects/{p['id']}", {"team_id": team["id"]}).raise_for_status()
    assert team_members(org.admin, team["id"]) == {org.m1.user_id, org.m2.user_id}
    other = org.admin.post("/teams", {"name": "Design"}).json()
    org.admin.patch(f"/projects/{p['id']}", {"team_id": other["id"]}).raise_for_status()
    assert team_members(org.admin, other["id"]) == {org.m1.user_id, org.m2.user_id}
    assert team_members(org.admin, team["id"]) == {org.m1.user_id, org.m2.user_id}  # the old team keeps them
