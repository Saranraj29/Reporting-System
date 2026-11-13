"""Where people may add tasks and whom they may assign them to:
Team Member: own projects, themselves.  Project owner: their project, its members (and manages its tasks).
Team Lead: projects of their team (and their own), their team.  Manager / Admin: everything."""

import pytest


@pytest.fixture
def world(org):
    """Apollo: Mia + Max (members).  Hermes: Olive (member), Mia (owner no, plain member), team Data with its own project Pipeline.
    Leo leads team Core (Mia, Max, Leo); Olive is outside the team."""
    o = org
    o.apollo = o.project
    o.hermes = o.admin.post("/projects", {"name": "Hermes"}).json()
    o.admin.put(f"/projects/{o.apollo['id']}/members", {"user_ids": [o.m1.user_id, o.m2.user_id]}).raise_for_status()
    o.admin.put(f"/projects/{o.hermes['id']}/members", {"user_ids": [o.out.user_id]}).raise_for_status()
    o.core_project = o.admin.post("/projects", {"name": "Core site", "team_ids": [o.team["id"]]}).json()  # a project of Leo's team, nobody a member yet
    return o


def create(api, project, assignees, title="t"):
    return api.post("/tasks", {"project_id": project["id"], "title": title, "assignee_ids": assignees})


def codes(r):
    return r.status_code, (r.json().get("code") if r.status_code >= 400 else None)


# ------------------------------------------------------------------ team member
def test_a_member_adds_tasks_only_to_projects_they_work_on(world):
    assert create(world.m1, world.apollo, [world.m1.user_id]).status_code == 201
    assert codes(create(world.m1, world.hermes, [world.m1.user_id])) == (403, "forbidden")  # not a member of Hermes
    assert codes(create(world.m1, world.core_project, [world.m1.user_id])) == (403, "forbidden")  # in the team, but a plain member: only the projects they work on
    # a task can only be moved to a project they work on, too
    t = create(world.m1, world.apollo, [world.m1.user_id]).json()
    assert world.m1.patch(f"/tasks/{t['id']}", {"project_id": world.hermes["id"]}).status_code == 403
    assert world.m1.patch(f"/tasks/{t['id']}", {"project_id": world.apollo["id"]}).status_code == 200


def test_a_member_can_only_assign_themselves(world):
    assert codes(create(world.m1, world.apollo, [world.m2.user_id])) == (403, "forbidden")  # even a fellow member of the project
    assert codes(create(world.m1, world.apollo, [world.m1.user_id, world.m2.user_id])) == (403, "forbidden")
    t = create(world.m1, world.apollo, [world.m1.user_id]).json()
    assert world.m1.put(f"/tasks/{t['id']}/assignees", {"user_ids": [world.m2.user_id]}).status_code == 403


def test_the_task_form_only_offers_what_the_person_may_use(world):
    mine = {p["name"]: p["can_add_tasks"] for p in world.m1.get("/projects").json()["items"]}
    assert mine == {"Apollo": True}  # only the projects that concern her are listed at all
    got = world.m1.get(f"/projects/{world.apollo['id']}/assignable-users").json()
    assert got["can_add_tasks"] is True and [u["name"] for u in got["items"]] == ["Mia Member"]
    assert world.m1.get(f"/projects/{world.hermes['id']}/assignable-users").json()["can_add_tasks"] is False
    assert all(p["can_add_tasks"] for p in world.mgr.get("/projects").json()["items"])


# ------------------------------------------------------------------ project owner
def test_an_owner_assigns_the_members_of_their_project_and_manages_its_tasks(world):
    world.admin.put(f"/projects/{world.apollo['id']}/members", {"user_ids": [world.m2.user_id], "owner_ids": [world.m1.user_id]}).raise_for_status()
    r = create(world.m1, world.apollo, [world.m1.user_id, world.m2.user_id], "for both")  # several members at once
    assert r.status_code == 201 and {a["name"] for a in r.json()["assignees"]} == {"Mia Member", "Max Member"}
    assert codes(create(world.m1, world.apollo, [world.out.user_id])) == (403, "forbidden")  # Olive does not work on Apollo
    assert codes(create(world.m1, world.hermes, [world.m1.user_id])) == (403, "forbidden")  # owning Apollo says nothing about Hermes
    got = world.m1.get(f"/projects/{world.apollo['id']}/assignable-users").json()
    assert {u["name"] for u in got["items"]} == {"Mia Member", "Max Member"}
    # the owner may edit and reassign every task of the project
    assert world.m1.patch(f"/tasks/{r.json()['id']}", {"priority": "urgent"}).status_code == 200
    assert world.m1.put(f"/tasks/{r.json()['id']}/assignees", {"user_ids": [world.m2.user_id]}).status_code == 200


# ------------------------------------------------------------------ team lead
def test_a_team_lead_also_assigns_the_members_of_their_teams_projects(world):
    # Olive works on the team's project but is not in the team itself (the project brought her in, then she was taken off the team list)
    world.admin.put(f"/projects/{world.core_project['id']}/members", {"user_ids": [world.out.user_id]}).raise_for_status()
    world.admin.put(f"/teams/{world.team['id']}/members", {"user_ids": [world.lead.user_id, world.m1.user_id, world.m2.user_id]}).raise_for_status()
    assert create(world.lead, world.core_project, [world.out.user_id, world.m1.user_id]).status_code == 201
    got = world.lead.get(f"/projects/{world.core_project['id']}/assignable-users").json()
    assert {u["name"] for u in got["items"]} == {"Leo Lead", "Mia Member", "Max Member", "Olive Outsider"}
    # only for that project: Olive is still nobody's to assign in a project of another kind
    world.admin.put(f"/projects/{world.hermes['id']}/members", {"user_ids": [world.out.user_id, world.lead.user_id]}).raise_for_status()
    assert codes(create(world.lead, world.hermes, [world.out.user_id])) == (403, "forbidden")


def test_a_team_lead_adds_tasks_to_their_teams_projects_and_assigns_their_team(world):
    assert create(world.lead, world.core_project, [world.m1.user_id, world.m2.user_id]).status_code == 201  # team project, no membership needed
    assert create(world.lead, world.apollo, [world.lead.user_id]).status_code == 403  # Apollo: not his team's, not a member
    assert codes(create(world.lead, world.hermes, [world.m1.user_id])) == (403, "forbidden")
    assert codes(create(world.lead, world.core_project, [world.out.user_id])) == (403, "forbidden")  # Olive is outside the team
    # a project he works on counts too
    world.admin.put(f"/projects/{world.hermes['id']}/members", {"user_ids": [world.out.user_id, world.lead.user_id]}).raise_for_status()
    assert create(world.lead, world.hermes, [world.m1.user_id]).status_code == 201


def test_several_hats_add_up(world):
    """Mia is a Team Member who also owns Hermes and leads a team: she gets the rights of each."""
    world.admin.put(f"/projects/{world.hermes['id']}/members", {"user_ids": [world.out.user_id], "owner_ids": [world.m1.user_id]}).raise_for_status()
    assert create(world.m1, world.hermes, [world.out.user_id, world.m1.user_id]).status_code == 201  # owner of Hermes
    assert create(world.m1, world.apollo, [world.m1.user_id]).status_code == 201  # member of Apollo


# ------------------------------------------------------------------ manager and admin
def test_managers_and_admins_are_not_restricted(world):
    for api in (world.mgr, world.admin):
        assert create(api, world.hermes, [world.out.user_id, world.m1.user_id, world.lead.user_id]).status_code == 201
        assert create(api, world.core_project, [world.m2.user_id]).status_code == 201
