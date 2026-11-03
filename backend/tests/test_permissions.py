from app.perms import PERMISSIONS, SEEDED_ROLES

from .conftest import role_id


def mk_task(api, project_id, title, **kw):
    r = api.post("/tasks", {"project_id": project_id, "title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_seeded_roles_only_use_known_keys_and_match_the_design():
    for name, (_, keys) in SEEDED_ROLES.items():
        assert set(keys) <= set(PERMISSIONS), name
    assert "report.performance.view.all" not in SEEDED_ROLES["Team Member"][1]
    assert not any("performance" in k for k in SEEDED_ROLES["Company Admin"][1])
    share = [n for n, (_, k) in SEEDED_ROLES.items() if "report.share.client" in k]
    assert sorted(share) == ["CEO / CTO", "Manager"]  # per design: Manager and CEO/CTO only


def test_task_visibility_follows_scope(org):
    o = org
    t1 = mk_task(o.m1, o.project["id"], "Mia task")
    t2 = mk_task(o.m2, o.project["id"], "Max task")
    t3 = mk_task(o.out, o.project["id"], "Olive task")
    ids = lambda api: {t["title"] for t in api.get("/tasks").json()["items"]}  # noqa: E731
    assert ids(o.m1) == {"Mia task"}  # own
    assert ids(o.lead) == {"Mia task", "Max task"}  # team (lead of Core)
    assert ids(o.mgr) == {"Mia task", "Max task", "Olive task"}  # all
    assert o.m1.get(f"/tasks/{t2['id']}").status_code == 404
    assert o.lead.get(f"/tasks/{t3['id']}").status_code == 404
    assert o.mgr.get(f"/tasks/{t1['id']}").status_code == 200


def test_edit_scope_and_assignment_scope(org):
    o = org
    t = mk_task(o.m1, o.project["id"], "Mia task")
    assert o.m2.patch(f"/tasks/{t['id']}", {"title": "hijack"}).status_code == 404  # cannot even see it
    assert o.m1.patch(f"/tasks/{t['id']}", {"title": "renamed"}).status_code == 200
    # a member may not assign someone else's name onto a task
    r = o.m1.post("/tasks", {"project_id": o.project["id"], "title": "x", "assignee_ids": [o.m2.user_id]})
    assert r.status_code == 403
    # a lead may assign within the team but not outside it
    ok = o.lead.post("/tasks", {"project_id": o.project["id"], "title": "team", "assignee_ids": [o.m1.user_id, o.m2.user_id]})
    assert ok.status_code == 201
    no = o.lead.post("/tasks", {"project_id": o.project["id"], "title": "out", "assignee_ids": [o.out.user_id]})
    assert no.status_code == 403
    # managers can assign anyone
    assert o.mgr.post("/tasks", {"project_id": o.project["id"], "title": "m", "assignee_ids": [o.out.user_id]}).status_code == 201


def test_reports_require_the_matching_permission(org):
    o = org
    assert o.m1.get("/reports").json()["items"] == []
    assert o.m1.get("/reports/weekly").status_code == 403
    assert {r["key"]: r["scope"] for r in o.lead.get("/reports").json()["items"]} == {"weekly": "team", "monthly": "team", "performance": "team"}
    assert {r["scope"] for r in o.mgr.get("/reports").json()["items"]} == {"all"}
    admin_keys = {r["key"] for r in o.admin.get("/reports").json()["items"]}
    assert admin_keys == {"weekly", "monthly"}  # no performance for Company Admin


def test_custom_role_and_union_of_roles(org):
    o = org
    perf = o.admin.post("/roles", {"name": "Auditor", "description": "perf only", "permissions": ["report.performance.view.all"]})
    assert perf.status_code == 201
    r = o.admin.patch(f"/users/{o.m1.user_id}", {"role_ids": [role_id(o.admin, "Team Member"), perf.json()["id"]]})
    assert r.status_code == 200
    # permissions are cached for 5 minutes by design, so drop the cache to observe the change
    from app.services.access import clear_permission_cache

    clear_permission_cache()
    perms = set(o.m1.get("/me").json()["permissions"])
    assert {"task.view.own", "report.performance.view.all"} <= perms  # union of both roles


def test_role_validation_and_deletion_rules(org):
    o = org
    assert o.admin.post("/roles", {"name": "Bad", "permissions": ["nope.nope"]}).status_code == 400
    assert o.admin.post("/roles", {"name": "Manager", "permissions": []}).status_code == 409
    mgr_role = role_id(o.admin, "Manager")
    assert o.admin.delete(f"/roles/{mgr_role}").status_code == 409  # in use
    empty = o.admin.post("/roles", {"name": "Temp"}).json()
    assert o.admin.delete(f"/roles/{empty['id']}").status_code == 204
    assert len(o.admin.get("/permissions").json()["items"]) == len(PERMISSIONS)


def test_non_admins_cannot_manage_users_roles_or_settings(org):
    o = org
    assert o.m1.post("/roles", {"name": "x"}).status_code == 403
    assert o.m1.post("/users", {"email": "a@acme.com", "name": "a", "password": "Passw0rd!pass"}).status_code == 403
    assert o.m1.patch("/settings", {"name": "Hacked"}).status_code == 403
    assert o.m1.post("/projects", {"name": "mine"}).status_code == 403
    assert o.lead.get("/roles").status_code == 403


def test_admin_cannot_lock_themselves_out(org):
    o = org
    admin_id = o.admin.user_id
    assert o.admin.patch(f"/users/{admin_id}", {"is_active": False}).status_code == 400
    assert o.admin.patch(f"/users/{admin_id}", {"role_ids": [role_id(o.admin, "Team Member")]}).status_code == 400


def test_deactivated_user_loses_access(org):
    o = org
    o.admin.patch(f"/users/{o.m2.user_id}", {"is_active": False}).raise_for_status()
    assert o.m2.get("/me").status_code == 401


def test_clients_hidden_from_regular_members(org):
    o = org
    assert o.m1.get("/clients").status_code == 403
    assert o.mgr.get("/clients").status_code == 200
