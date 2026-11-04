from app.services.dashboard import clear_dashboard_cache


def test_dashboard_numbers_for_a_manager(work):
    d = work.mgr.get("/dashboard").json()
    assert d["tasks_by_status"] == {"todo": 2, "in_progress": 1, "in_review": 0, "testing": 0, "blocked": 1, "done": 1}
    assert d["total_tasks"] == 5
    assert d["total_hours"] == 10.0
    assert {h["project"]: h["hours"] for h in d["hours_by_project"]} == {"Apollo": 9.0, "Hermes": 1.0}
    assert d["overdue_count"] == 1 and d["overdue_tasks"][0]["title"] == "Write docs"
    assert d["blocked_count"] == 1 and d["blockers"][0]["title"] == "Fix pipeline"
    assert sum(a["hours"] for a in d["hours_by_activity"]) == 10.0
    assert d["daily_status"]["expected"] == 6


def test_dashboard_is_filtered_by_permission_scope(work):
    assert work.m1.get("/dashboard").json()["total_hours"] == 4.0  # own: Mia 3h + 1h
    lead = work.lead.get("/dashboard").json()
    assert lead["total_hours"] == 6.0  # team (Leo, Mia, Max) — Olive's 4h excluded
    assert lead["daily_status"]["expected"] == 3
    assert work.out.get("/dashboard").json()["total_hours"] == 4.0


def test_dashboard_filters(work):
    d = work.mgr.get("/dashboard", params={"project": work.hermes["id"]}).json()
    assert d["total_hours"] == 1.0 and d["total_tasks"] == 1
    d = work.mgr.get("/dashboard", params={"user": work.m2.user_id}).json()
    assert d["total_hours"] == 2.0
    # a lead filtering on someone outside the team gets an empty dashboard, not their data
    d = work.lead.get("/dashboard", params={"user": work.out.user_id}).json()
    assert d["total_hours"] == 0 and d["total_tasks"] == 0
    assert work.mgr.get("/dashboard", params={"from": "2026-02-02", "to": "2026-02-01"}).status_code == 400


def test_dashboard_blockers_from_daily_status(work):
    work.m1.put(f"/daily-status/{work.today}", {"did_today": "x", "blockers": "Need staging access"}).raise_for_status()
    clear_dashboard_cache()
    d = work.mgr.get("/dashboard").json()
    assert d["daily_status"]["submitted_today"] == 1
    assert d["daily_status"]["blockers"][0]["text"] == "Need staging access"


def test_dashboard_is_cached_for_60_seconds(work, owner_conn):
    first = work.mgr.get("/dashboard").json()
    owner_conn.execute("DELETE FROM time_entries")
    assert work.mgr.get("/dashboard").json() == first  # still cached
    clear_dashboard_cache()
    assert work.mgr.get("/dashboard").json()["total_hours"] == 0


def test_member_without_dashboard_permission_is_rejected(org):
    # a role with no dashboard key
    org.admin.post("/roles", {"name": "Bare", "permissions": ["task.view.own"]}).raise_for_status()
    r = org.admin.post("/users", {"email": "bare@acme.com", "name": "Bare", "password": "Passw0rd!pass",
                                  "role_ids": [next(x["id"] for x in org.admin.get("/roles").json()["items"] if x["name"] == "Bare")]})
    assert r.status_code == 201
    from .conftest import login

    assert login(org.client, "bare@acme.com").get("/dashboard").status_code == 403
