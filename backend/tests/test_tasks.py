import datetime as dt

from .conftest import uid


def mk(api, project_id, title="T", **kw):
    r = api.post("/tasks", {"project_id": project_id, "title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def today():
    return dt.date.today().isoformat()


def test_create_task_with_fixed_and_custom_fields(org):
    o = org
    f = o.admin.post("/task-fields", {"key": "ticket_ref", "label": "Ticket", "type": "text", "required": True})
    assert f.status_code == 201
    o.admin.post("/task-fields", {"key": "risk", "label": "Risk", "type": "select", "options": ["low", "high"]}).raise_for_status()
    base = {"project_id": o.project["id"], "title": "Build login"}
    r = o.m1.post("/tasks", base)  # required custom field missing
    assert r.status_code == 400 and r.json()["details"] == {"ticket_ref": "required"}
    r = o.m1.post("/tasks", {**base, "custom_fields": {"ticket_ref": "T-1", "risk": "extreme"}})
    assert r.status_code == 400 and "risk" in r.json()["details"]
    r = o.m1.post("/tasks", {**base, "custom_fields": {"ticket_ref": "T-1", "mystery": 1}})
    assert r.status_code == 400 and r.json()["details"]["mystery"] == "unknown field"
    ok = o.m1.post("/tasks", {**base, "custom_fields": {"ticket_ref": "T-1", "risk": "high"}, "eta_hours": 6, "activity_type": "Testing"})
    assert ok.status_code == 201
    t = ok.json()
    assert t["custom_fields"] == {"ticket_ref": "T-1", "risk": "high"}
    assert [a["id"] for a in t["assignees"]] == [o.m1.user_id]  # defaults to the creator
    assert o.m1.post("/tasks", {**base, "custom_fields": {"ticket_ref": "x"}, "activity_type": "Nonsense"}).status_code == 400


def test_hidden_builtin_fields_and_field_admin(org):
    o = org
    fields = {f["key"]: f for f in o.admin.get("/task-fields").json()["items"]}
    assert fields["eta_hours"]["is_builtin"]
    r = o.admin.patch(f"/task-fields/{fields['eta_hours']['id']}", {"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False  # hidden, not dropped
    assert o.admin.patch(f"/task-fields/{fields['eta_hours']['id']}", {"required": True}).status_code == 400
    assert o.admin.post("/task-fields", {"key": "dup", "label": "d", "type": "select"}).status_code == 400  # select needs options
    assert o.m1.post("/task-fields", {"key": "zz", "label": "z", "type": "text"}).status_code == 403


def test_actual_hours_is_the_sum_of_every_assignee_time_entries(org):
    o = org
    t = mk(o.lead, o.project["id"], "Shared", assignee_ids=[o.m1.user_id, o.m2.user_id])
    assert o.m1.post("/time-entries", {"task_id": t["id"], "hours": 2.5}).status_code == 201
    assert o.m2.post("/time-entries", {"task_id": t["id"], "hours": 1.5, "note": "review"}).status_code == 201
    got = o.lead.get(f"/tasks/{t['id']}").json()
    assert got["actual_hours"] == 4.0
    entries = o.lead.get("/time-entries", params={"task": t["id"]}).json()["items"]
    assert sorted(e["hours"] for e in entries) == [1.5, 2.5]
    assert {e["user_name"] for e in entries} == {"Mia Member", "Max Member"}


def test_time_entry_rules(org):
    o = org
    t = mk(o.m1, o.project["id"], "Mine")
    assert o.m2.post("/time-entries", {"task_id": t["id"], "hours": 1}).status_code in (403, 404)  # not assigned to Max
    assert o.m1.post("/time-entries", {"task_id": t["id"], "hours": 0}).status_code == 422
    assert o.m1.post("/time-entries", {"task_id": t["id"], "hours": 25}).status_code == 422
    future = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    assert o.m1.post("/time-entries", {"task_id": t["id"], "hours": 1, "entry_date": future}).status_code == 400
    e = o.m1.post("/time-entries", {"task_id": t["id"], "hours": 1}).json()
    assert o.m2.patch(f"/time-entries/{e['id']}", {"hours": 9}).status_code == 403
    assert o.m1.patch(f"/time-entries/{e['id']}", {"hours": 3}).json()["hours"] == 3
    assert o.m1.delete(f"/time-entries/{e['id']}").status_code == 204


def test_timer_start_stop_and_single_running_timer(org):
    o = org
    t = mk(o.m1, o.project["id"], "Timed")
    t2 = mk(o.m1, o.project["id"], "Timed 2")
    e = o.m1.post("/time-entries/start", {"task_id": t["id"]})
    assert e.status_code == 201 and e.json()["running"]
    dup = o.m1.post("/time-entries/start", {"task_id": t2["id"]})
    assert dup.status_code == 409 and dup.json()["code"] == "timer_running"
    assert o.m2.post(f"/time-entries/{e.json()['id']}/stop").status_code == 404  # someone else's timer
    stopped = o.m1.post(f"/time-entries/{e.json()['id']}/stop")
    assert stopped.status_code == 200 and not stopped.json()["running"]
    assert o.m1.post(f"/time-entries/{e.json()['id']}/stop").status_code == 409  # already stopped
    assert o.m1.post("/time-entries/start", {"task_id": t2["id"]}).status_code == 201  # free again


def test_timer_hours_are_computed_from_timestamps(org, owner_conn):
    o = org
    t = mk(o.m1, o.project["id"], "Timed")
    e = o.m1.post("/time-entries/start", {"task_id": t["id"]}).json()
    owner_conn.execute("UPDATE time_entries SET started_at = now() - interval '90 minutes' WHERE id = %s", (e["id"],))
    assert o.m1.post(f"/time-entries/{e['id']}/stop").json()["hours"] == 1.5


def test_blocking_a_task_sets_flag_and_queues_one_notification_job(org, owner_conn):
    o = org
    t = mk(o.m1, o.project["id"], "Stuck")
    r = o.m1.patch(f"/tasks/{t['id']}", {"status": "blocked"})
    assert r.status_code == 200 and r.json()["is_blocked"]
    jobs = owner_conn.execute("SELECT kind FROM jobs WHERE kind = 'notify.blocker'").fetchall()
    assert len(jobs) == 1
    o.m1.patch(f"/tasks/{t['id']}", {"title": "Stuck still"})  # no status change: no second job
    assert owner_conn.execute("SELECT count(*) FROM jobs WHERE kind = 'notify.blocker'").fetchone()[0] == 1
    r = o.m1.patch(f"/tasks/{t['id']}", {"status": "in_progress"})
    assert r.json()["is_blocked"] is False


def test_done_sets_completed_at_and_reopen_clears_it(org):
    o = org
    t = mk(o.m1, o.project["id"], "Finish")
    done = o.m1.patch(f"/tasks/{t['id']}", {"status": "done"}).json()
    assert done["completed_at"]
    assert o.m1.patch(f"/tasks/{t['id']}", {"status": "todo"}).json()["completed_at"] is None


def test_filters_pagination_and_overdue(org):
    o = org
    yesterday = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    mk(o.mgr, o.project["id"], "Late one", due_date=yesterday, priority="urgent", assignee_ids=[o.m1.user_id])
    mk(o.mgr, o.project["id"], "Fine", assignee_ids=[o.m2.user_id])
    r = o.mgr.get("/tasks", params={"overdue": "true"}).json()
    assert [t["title"] for t in r["items"]] == ["Late one"] and r["items"][0]["overdue"]
    assert o.mgr.get("/tasks", params={"assignee": o.m2.user_id}).json()["total"] == 1
    assert o.mgr.get("/tasks", params={"priority": "urgent"}).json()["total"] == 1
    assert o.mgr.get("/tasks", params={"q": "fine"}).json()["total"] == 1
    page = o.mgr.get("/tasks", params={"limit": 1, "page": 2}).json()
    assert page["total"] == 2 and len(page["items"]) == 1 and page["limit"] == 1
    assert o.mgr.get("/tasks", params={"limit": 201}).status_code == 422  # max 200


def test_assignees_endpoint_and_comments(org):
    o = org
    t = mk(o.lead, o.project["id"], "Pair", assignee_ids=[o.m1.user_id])
    r = o.lead.put(f"/tasks/{t['id']}/assignees", {"user_ids": [o.m1.user_id, o.m2.user_id]})
    assert r.status_code == 200 and len(r.json()["assignees"]) == 2
    assert o.lead.put(f"/tasks/{t['id']}/assignees", {"user_ids": []}).status_code == 400
    c = o.m2.post(f"/tasks/{t['id']}/comments", {"body": "On it"})
    assert c.status_code == 201
    assert [x["body"] for x in o.m1.get(f"/tasks/{t['id']}/comments").json()["items"]] == ["On it"]
    assert o.out.get(f"/tasks/{t['id']}/comments").status_code == 404


def test_invalid_inputs_use_the_error_format(org):
    o = org
    r = o.m1.post("/tasks", {"project_id": uid(), "title": "x"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_project"
    r = o.m1.post("/tasks", {"project_id": o.project["id"], "title": ""})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    r = o.m1.post("/tasks", {"project_id": o.project["id"], "title": "d", "start_date": "2026-05-10", "due_date": "2026-05-01"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_dates"
    assert o.m1.get(f"/tasks/{uid()}").status_code == 404


def test_archived_project_rejects_tasks(org):
    o = org
    o.admin.patch(f"/projects/{o.project['id']}", {"status": "archived"}).raise_for_status()
    assert o.m1.post("/tasks", {"project_id": o.project["id"], "title": "x"}).json()["code"] == "project_archived"


def test_delete_task(org):
    o = org
    t = mk(o.m1, o.project["id"], "Gone")
    assert o.m2.delete(f"/tasks/{t['id']}").status_code == 404
    assert o.m1.delete(f"/tasks/{t['id']}").status_code == 204
    assert o.m1.get(f"/tasks/{t['id']}").status_code == 404


# ---------------------------------------------------------------- daily status
def test_daily_status_upsert_one_row_per_day(org):
    o = org
    d = today()
    r = o.m1.put(f"/daily-status/{d}", {"did_today": "API", "next_up": "UI", "blockers": ""})
    assert r.status_code == 200
    r2 = o.m1.put(f"/daily-status/{d}", {"did_today": "API v2", "next_up": "UI", "blockers": "waiting on keys"})
    assert r2.json()["id"] == r.json()["id"] and r2.json()["did_today"] == "API v2"
    items = o.m1.get("/daily-status").json()["items"]
    assert len(items) == 1 and items[0]["blockers"] == "waiting on keys"


def test_daily_status_locked_after_the_day_and_not_in_the_future(org):
    o = org
    y = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    tmr = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    r = o.m1.put(f"/daily-status/{y}", {"did_today": "late edit"})
    assert r.status_code == 403 and r.json()["code"] == "status_locked"
    assert o.m1.put(f"/daily-status/{tmr}", {"did_today": "x"}).status_code == 400


def test_daily_status_visibility_scopes(org):
    o = org
    d = today()
    for who, txt in ((o.m1, "mia"), (o.m2, "max"), (o.out, "olive")):
        who.put(f"/daily-status/{d}", {"did_today": txt}).raise_for_status()
    names = lambda api: sorted(i["user_name"] for i in api.get("/daily-status").json()["items"])  # noqa: E731
    assert names(o.m1) == ["Mia Member"]
    assert names(o.lead) == ["Max Member", "Mia Member"]
    assert len(names(o.mgr)) == 3


def test_company_timezone_decides_which_day_is_today(org):
    o = org
    o.admin.patch("/settings", {"timezone": "Pacific/Kiritimati"}).raise_for_status()  # UTC+14
    from app.services.timeutil import company_today

    local = company_today("Pacific/Kiritimati").isoformat()
    assert o.m1.put(f"/daily-status/{local}", {"did_today": "tz"}).status_code == 200


