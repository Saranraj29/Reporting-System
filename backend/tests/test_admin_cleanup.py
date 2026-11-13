"""People see only the projects and teams that concern them; project owners get reports for their own projects; things can be deleted
(users without history, projects, clients, teams, generated reports) with a confirmation when something would go with them."""

import pytest

from .conftest import add_user, drain


@pytest.fixture
def world(work):
    """Apollo: Mia, Max, Olive, Leo (members).  Hermes: nobody but admin's tasks.  Team Core (Leo leads; Mia, Max members)."""
    work.apollo = work.project
    return work


# ------------------------------------------------------------------ lists show only what concerns the person
def test_a_member_sees_only_their_projects_and_teams(world):
    names = lambda api, path: {x["name"] for x in api.get(path).json()["items"]}  # noqa: E731
    sumit = add_user(world.admin, "Sumit Single", "Team Member")  # one project, no team of their own
    world.admin.put(f"/projects/{world.hermes['id']}/members", {"user_ids": [sumit.user_id]}).raise_for_status()
    team = world.admin.post("/teams", {"name": "Data"}).json()
    world.admin.patch(f"/projects/{world.hermes['id']}", {"team_ids": [team["id"]]}).raise_for_status()  # his project belongs to team Data
    assert names(sumit, "/projects") == {"Hermes"}  # not Apollo, not every project of the company
    assert names(sumit, "/teams") == {"Data"}  # the team of his project, not Core
    assert names(world.m1, "/projects") == {"Apollo", "Hermes"}  # Mia also has a task in Hermes, so it concerns her
    assert names(world.m1, "/teams") == {"Core", "Data"}  # her own team, and the team that owns Hermes


def test_leads_managers_and_admins_see_what_their_role_covers(world):
    names = lambda api, path: {x["name"] for x in api.get(path).json()["items"]}  # noqa: E731
    core_site = world.admin.post("/projects", {"name": "Core site", "team_ids": [world.team["id"]]}).json()
    assert "Core site" in names(world.lead, "/projects") and names(world.lead, "/teams") == {"Core"}  # his team's project
    for api in (world.mgr, world.admin):
        assert {"Apollo", "Hermes", "Core site"} <= names(api, "/projects") and "Core" in names(api, "/teams")
    assert core_site["id"]


# ------------------------------------------------------------------ project owner reports
def make_owner(world, user, project):
    members = [m for m in world.admin.get(f"/projects/{project['id']}/members").json()["user_ids"] if m != user.user_id]
    world.admin.put(f"/projects/{project['id']}/members", {"user_ids": members, "owner_ids": [user.user_id]}).raise_for_status()


def test_a_project_owner_gets_reports_for_their_own_projects_only(world):
    assert world.m1.get("/reports").json()["items"] == []  # an ordinary member has none
    assert world.m1.get("/reports/weekly").status_code == 403
    make_owner(world, world.m1, world.apollo)
    listed = {r["key"]: r["scope"] for r in world.m1.get("/reports").json()["items"]}
    assert listed == {"weekly": "my projects", "monthly": "my projects", "visibility": "my projects"}  # not the per-person performance report
    assert world.m1.get("/reports/performance").status_code == 403
    rep = world.m1.get("/reports/weekly").json()["figures"]
    assert {p["project"] for p in rep["projects"]} == {"Apollo"}  # Hermes is not hers
    assert rep["totals"]["hours"] == 9.0  # everybody's time in Apollo (Mia 3, Max 2, Olive 4), not only her own
    assert "check_ins" not in rep and "check_in_entries" not in rep  # daily-status text is never widened by ownership
    vis = world.m1.get("/reports/visibility").json()["figures"]
    assert [p["name"] for p in vis["projects"]] == ["Apollo"]
    assert world.m1.get("/reports/weekly", params={"project": world.hermes["id"]}).status_code == 403
    assert world.m1.get("/reports/weekly", params={"project": world.apollo["id"]}).status_code == 200


def test_an_owners_export_stays_inside_their_projects(world):
    make_owner(world, world.m1, world.apollo)
    r = world.m1.post("/reports/weekly/export", params={"format": "md"})
    assert r.status_code == 202
    drain()
    run = world.m1.get(f"/report-runs/{r.json()['id']}").json()
    assert run["status"] == "ready" and {p["project"] for p in run["figures"]["projects"]} == {"Apollo"} and "check_ins" not in run["figures"]


def test_someone_with_the_report_permission_keeps_their_normal_scope(world):
    make_owner(world, world.lead, world.apollo)  # a lead who also owns a project
    assert {r["scope"] for r in world.lead.get("/reports").json()["items"]} == {"team"}


# ------------------------------------------------------------------ deleting
def test_a_project_with_tasks_needs_a_confirmation_and_takes_its_tasks_along(world, owner_conn):
    r = world.admin.delete(f"/projects/{world.hermes['id']}")
    assert r.status_code == 409 and r.json()["code"] == "in_use" and "1 task" in r.json()["message"]
    assert owner_conn.execute("select count(*) from projects where name = 'Hermes'").fetchone()[0] == 1
    assert world.admin.delete(f"/projects/{world.hermes['id']}", params={"force": "true"}).status_code == 204
    assert owner_conn.execute("select count(*) from projects where name = 'Hermes'").fetchone()[0] == 0
    assert owner_conn.execute("select count(*) from tasks where title = 'Fix pipeline'").fetchone()[0] == 0  # its task and the time on it went too
    empty = world.admin.post("/projects", {"name": "Scratch"}).json()
    assert world.admin.delete(f"/projects/{empty['id']}").status_code == 204  # nothing in it: no confirmation needed
    assert world.mgr.delete(f"/projects/{world.apollo['id']}", params={"force": "true"}).status_code == 204  # managers hold project.manage
    assert world.m1.delete(f"/projects/{world.apollo['id']}").status_code == 403


def test_deleting_a_client_keeps_its_projects(world, owner_conn):
    assert world.admin.delete(f"/clients/{world.globex['id']}").status_code == 409  # Apollo belongs to Globex
    assert world.admin.delete(f"/clients/{world.globex['id']}", params={"force": "true"}).status_code == 204
    assert world.admin.get("/projects").json()["items"][0]["client_id"] is None or all(p["client_id"] is None for p in world.admin.get("/projects").json()["items"])
    assert "Apollo" in {p["name"] for p in world.admin.get("/projects").json()["items"]}
    assert world.m1.delete(f"/clients/{world.globex['id']}").status_code in (403, 404)


def test_deleting_a_team_keeps_its_projects(world):
    world.admin.patch(f"/projects/{world.apollo['id']}", {"team_ids": [world.team["id"]]}).raise_for_status()
    r = world.admin.delete(f"/teams/{world.team['id']}")
    assert r.status_code == 409 and r.json()["code"] == "in_use" and "1 project" in r.json()["message"]
    assert world.admin.delete(f"/teams/{world.team['id']}", params={"force": "true"}).status_code == 204
    apollo = next(p for p in world.admin.get("/projects").json()["items"] if p["name"] == "Apollo")
    assert apollo["team_ids"] == []
    assert world.admin.get("/teams").json()["items"] == []
    assert world.m1.delete(f"/teams/{world.team['id']}").status_code in (403, 404)


def test_a_user_without_history_can_be_deleted_one_with_history_is_deactivated_instead(world, owner_conn):
    r = world.admin.delete(f"/users/{world.m1.user_id}")  # Mia has tasks, hours and check-ins
    assert r.status_code == 409 and r.json()["code"] == "has_history" and "Deactivate" in r.json()["message"]
    assert r.json()["details"]["tasks"] >= 1 and r.json()["details"]["time_entries"] >= 1
    fresh = add_user(world.admin, "Nina New", "Team Member")
    assert world.admin.delete(f"/users/{fresh.user_id}").status_code == 204
    assert owner_conn.execute("select count(*) from users where name = 'Nina New'").fetchone()[0] == 0
    assert world.admin.delete(f"/users/{world.admin.user_id}").json()["code"] == "cannot_delete_self"
    assert world.m1.delete(f"/users/{world.m2.user_id}").status_code == 403


def test_a_generated_report_can_be_deleted_by_whoever_may_open_it(world, owner_conn):
    run_id = world.admin.post("/reports/weekly/export", params={"format": "md"}).json()["id"]
    drain()
    assert world.mgr.delete(f"/report-runs/{run_id}").status_code == 403  # an export belongs to its requester
    assert world.admin.delete(f"/report-runs/{run_id}").status_code == 204
    assert world.admin.get(f"/report-runs/{run_id}").status_code == 404
    assert owner_conn.execute("select count(*) from report_runs").fetchone()[0] == 0
    queued = world.admin.post("/reports/weekly/export", params={"format": "md"}).json()["id"]  # not drained: still being generated
    r = world.admin.delete(f"/report-runs/{queued}")
    assert r.status_code == 409 and r.json()["code"] == "run_busy"


# ------------------------------------------------------------------ filters on the project and client lists
def test_projects_and_clients_can_be_filtered(world):
    names = lambda r: {x["name"] for x in r.json()["items"]}  # noqa: E731
    internal = world.admin.post("/projects", {"name": "Internal tools"}).json()  # no client
    assert names(world.admin.get("/projects", params={"internal": "true"})) == {"Hermes", "Internal tools"}  # Hermes has no client either
    assert names(world.admin.get("/projects", params={"internal": "false"})) == {"Apollo"}
    assert names(world.admin.get("/projects", params={"client_id": world.globex["id"]})) == {"Apollo"}
    assert names(world.admin.get("/projects", params={"status": "archived"})) == set()
    world.admin.patch(f"/projects/{internal['id']}", {"status": "on_hold"}).raise_for_status()
    assert names(world.admin.get("/projects", params={"status": "on_hold"})) == {"Internal tools"}
    lonely = world.admin.post("/clients", {"name": "Lonely Ltd"}).json()
    assert names(world.admin.get("/clients", params={"has_projects": "true"})) == {"Globex"}
    assert names(world.admin.get("/clients", params={"has_projects": "false"})) == {"Lonely Ltd"} and lonely["id"]
    assert names(world.admin.get("/clients")) == {"Globex", "Lonely Ltd"}
