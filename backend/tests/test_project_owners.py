"""Project owners see every task in their project, whoever created it or is assigned to it."""

import pytest

from .conftest import add_user


@pytest.fixture
def proj(org):
    """Apollo (owner: Mia) has tasks from Max and Olive; Hermes (no owner) has one from Olive."""
    o = org
    hermes = o.admin.post("/projects", {"name": "Hermes"}).json()
    mk = lambda api, project, title: api.post("/tasks", {"project_id": project["id"], "title": title}).json()  # noqa: E731
    o.t_mia = mk(o.m1, o.project, "Mia task")
    o.t_max = mk(o.m2, o.project, "Max task in Apollo")
    o.t_olive = mk(o.out, o.project, "Olive task in Apollo")
    o.t_hermes = mk(o.out, hermes, "Olive task in Hermes")
    o.hermes = hermes
    for api, t, h in ((o.m2, o.t_max, 2), (o.out, o.t_olive, 3), (o.out, o.t_hermes, 5)):
        api.post("/time-entries", {"task_id": t["id"], "hours": h}).raise_for_status()
    return o


def make_owner(o, user, project=None):
    project = project or o.project
    r = o.admin.put(f"/projects/{project['id']}/members", {"user_ids": [], "owner_ids": [user.user_id]})
    assert r.status_code == 200, r.text
    return r.json()


def titles(api, **params):
    return {t["title"] for t in api.get("/tasks", params=params).json()["items"]}


def test_without_ownership_a_member_only_sees_own_tasks(proj):
    assert titles(proj.m1) == {"Mia task"}


def test_owner_sees_all_tasks_in_their_project_only(proj):
    make_owner(proj, proj.m1)
    assert titles(proj.m1) == {"Mia task", "Max task in Apollo", "Olive task in Apollo"}  # not the Hermes task
    assert proj.m1.get(f"/tasks/{proj.t_olive['id']}").status_code == 200
    assert proj.m1.get(f"/tasks/{proj.t_hermes['id']}").status_code == 404
    # filters still work on top of ownership
    assert titles(proj.m1, assignee=proj.m2.user_id) == {"Max task in Apollo"}
    assert titles(proj.m1, project=proj.hermes["id"]) == set()
    # comments are readable and writable on tasks they can see
    assert proj.m1.post(f"/tasks/{proj.t_max['id']}/comments", {"body": "How is it going?"}).status_code == 201
    assert len(proj.m2.get(f"/tasks/{proj.t_max['id']}/comments").json()["items"]) == 1


def test_owner_view_does_not_grant_edit_rights(proj):
    make_owner(proj, proj.m1)
    detail = proj.m1.get(f"/tasks/{proj.t_max['id']}").json()
    assert detail["can_edit"] is False
    assert proj.m1.patch(f"/tasks/{proj.t_max['id']}", {"title": "hijacked"}).status_code == 403
    assert proj.m1.delete(f"/tasks/{proj.t_max['id']}").status_code == 403


def test_owner_sees_time_entries_of_everyone_in_the_project(proj):
    make_owner(proj, proj.m1)
    items = proj.m1.get("/time-entries").json()["items"]
    assert {(e["user_name"], e["hours"]) for e in items} == {("Max Member", 2.0), ("Olive Outsider", 3.0)}  # Hermes' 5h is not theirs


def test_owner_dashboard_covers_the_whole_project(proj):
    make_owner(proj, proj.m1)
    d = proj.m1.get("/dashboard").json()
    assert d["total_hours"] == 5.0 and d["total_tasks"] == 3  # Apollo only
    assert {h["project"] for h in d["hours_by_project"]} == {"Apollo"}
    # person filter on someone outside their scope: only that person's work inside the owned project
    d = proj.m1.get("/dashboard", params={"user": proj.out.user_id}).json()
    assert d["total_hours"] == 3.0 and d["total_tasks"] == 1
    # daily-status text is never widened by ownership
    proj.out.put(f"/daily-status/{__import__('datetime').date.today()}", {"did_today": "private standup"}).raise_for_status()
    from app.services.dashboard import clear_dashboard_cache

    clear_dashboard_cache()
    assert proj.m1.get("/dashboard", params={"user": proj.out.user_id}).json()["daily_status"]["submitted_today"] == 0


def test_non_owner_dashboard_unchanged(proj):
    d = proj.m1.get("/dashboard").json()
    assert d["total_hours"] == 0 and d["total_tasks"] == 1
    d = proj.m1.get("/dashboard", params={"user": proj.out.user_id}).json()
    assert d["total_hours"] == 0 and d["total_tasks"] == 0  # cannot peek at others


def test_several_owners_and_revocation(proj):
    proj.admin.put(f"/projects/{proj.project['id']}/members", {"user_ids": [proj.m2.user_id], "owner_ids": [proj.m1.user_id, proj.lead.user_id]})
    assert "Olive task in Apollo" in titles(proj.m1)
    p = next(x for x in proj.admin.get("/projects").json()["items"] if x["name"] == "Apollo")
    assert sorted(p["owner_ids"]) == sorted([proj.m1.user_id, proj.lead.user_id])
    assert set(p["member_ids"]) == {proj.m1.user_id, proj.m2.user_id, proj.lead.user_id}  # owners are members too
    # remove ownership: access disappears immediately
    proj.admin.put(f"/projects/{proj.project['id']}/members", {"user_ids": [proj.m1.user_id], "owner_ids": []})
    assert titles(proj.m1) == {"Mia task"}


def test_only_project_managers_can_assign_owners_and_owners_must_exist(proj):
    body = {"user_ids": [], "owner_ids": [proj.m1.user_id]}
    assert proj.m1.put(f"/projects/{proj.project['id']}/members", body).status_code == 403  # cannot self-promote
    assert proj.mgr.put(f"/projects/{proj.project['id']}/members", body).status_code == 200  # Manager has project.manage
    bad = proj.admin.put(f"/projects/{proj.project['id']}/members", {"user_ids": [], "owner_ids": ["00000000-0000-0000-0000-000000000009"]})
    assert bad.status_code == 400


def test_ownership_is_per_company(proj, client):
    from .conftest import signup_admin

    other = signup_admin(client, "globex.com", "Globex")
    r = other.put(f"/projects/{proj.project['id']}/members", {"user_ids": [], "owner_ids": [other.user_id]})
    assert r.status_code == 404  # another company's project does not exist for them


def test_company_admin_sees_every_project_and_every_task(proj):
    assert titles(proj.admin) == {"Mia task", "Max task in Apollo", "Olive task in Apollo", "Olive task in Hermes"}
    d = proj.admin.get("/dashboard").json()
    assert d["total_hours"] == 10.0 and {h["project"] for h in d["hours_by_project"]} == {"Apollo", "Hermes"}
    assert len(proj.admin.get("/time-entries").json()["items"]) == 3
    # the Manager and CEO/CTO roles also see everything
    assert titles(proj.mgr) == titles(proj.admin)
    ceo = add_user(proj.admin, "Carl Ceo", "CEO / CTO")
    assert titles(ceo) == titles(proj.admin)
