"""Fixes from the QA list: lost updates, time on finished tasks, the 24-hour day, a fresh dashboard, who may delete, task order, error wording, the assistant's list."""

import datetime as dt

import pytest

from .conftest import grant_assistant_to_members
from .test_assistant import ask, script, sentences


def detail(api, task):
    return api.get(f"/tasks/{task['id']}").json()


# ------------------------------------------------------------------ 1: two people editing one task
def test_a_stale_edit_is_refused_instead_of_silently_overwriting(work):
    t = work.tasks["t2"]  # Max's task; Max and the manager can both edit it
    opened = detail(work.m2, t)["updated_at"]  # both open it at the same moment
    assert work.m2.patch(f"/tasks/{t['id']}", {"status": "in_review", "expected_updated_at": opened}).status_code == 200
    r = work.mgr.patch(f"/tasks/{t['id']}", {"status": "done", "expected_updated_at": opened})  # the manager's form is now stale
    assert r.status_code == 409 and r.json()["code"] == "edited_elsewhere" and "Someone else changed this task" in r.json()["message"]
    assert detail(work.m2, t)["status"] == "in_review"  # the first save stands, nothing was lost silently
    fresh = detail(work.mgr, t)["updated_at"]
    assert work.mgr.patch(f"/tasks/{t['id']}", {"status": "done", "expected_updated_at": fresh}).status_code == 200  # reloaded: fine
    assert work.mgr.patch(f"/tasks/{t['id']}", {"priority": "high"}).status_code == 200  # a client that sends no timestamp is not blocked


def test_changing_assignees_also_counts_as_a_change(work):
    t = work.tasks["t2"]
    opened = detail(work.mgr, t)["updated_at"]
    assert work.mgr.put(f"/tasks/{t['id']}/assignees", {"user_ids": [work.m2.user_id, work.m1.user_id], "expected_updated_at": opened}).status_code == 200
    r = work.mgr.patch(f"/tasks/{t['id']}", {"priority": "low", "expected_updated_at": opened})
    assert r.status_code == 409 and r.json()["code"] == "edited_elsewhere"
    r = work.mgr.put(f"/tasks/{t['id']}/assignees", {"user_ids": [work.m2.user_id], "expected_updated_at": opened})
    assert r.status_code == 409


# ------------------------------------------------------------------ 2: no time on a finished task
def test_no_timer_and_no_time_on_a_finished_task(work):
    done = work.tasks["t1"]  # Mia's task, done
    r = work.m1.post("/time-entries", {"task_id": done["id"], "hours": 1})
    assert r.status_code == 409 and r.json()["code"] == "task_done"
    assert work.m1.post("/time-entries/start", {"task_id": done["id"]}).json()["code"] == "task_done"
    work.m1.patch(f"/tasks/{done['id']}", {"status": "in_progress"}).raise_for_status()  # reopened
    assert work.m1.post("/time-entries", {"task_id": done["id"], "hours": 1}).status_code == 201


# ------------------------------------------------------------------ 3: a day has 24 hours
def test_a_day_has_only_24_hours(work):
    yesterday = (work.today - dt.timedelta(days=1)).isoformat()
    task = work.tasks["t4"]  # Mia's open task
    assert work.m1.post("/time-entries", {"task_id": task["id"], "hours": 24, "entry_date": yesterday}).status_code == 201
    r = work.m1.post("/time-entries", {"task_id": task["id"], "hours": 24, "entry_date": yesterday})
    assert r.status_code == 409 and r.json()["code"] == "daily_limit" and "already have 24 h" in r.json()["message"]
    r = work.m1.post("/time-entries", {"task_id": task["id"], "hours": 0.25, "entry_date": yesterday})
    assert r.status_code == 409  # not even a quarter of an hour more
    other = (work.today - dt.timedelta(days=2)).isoformat()
    first = work.m1.post("/time-entries", {"task_id": task["id"], "hours": 10, "entry_date": other}).json()
    second = work.m1.post("/time-entries", {"task_id": task["id"], "hours": 10, "entry_date": other}).json()
    assert work.m1.patch(f"/time-entries/{first['id']}", {"hours": 14}).status_code == 200  # 14 + 10 = 24
    r = work.m1.patch(f"/time-entries/{first['id']}", {"hours": 15})
    assert r.status_code == 409 and "at most" in r.json()["message"]
    assert work.m1.patch(f"/time-entries/{second['id']}", {"entry_date": yesterday}).status_code == 409  # moving it to a full day
    assert work.m2.post("/time-entries", {"task_id": work.tasks["t2"]["id"], "hours": 24, "entry_date": yesterday}).status_code == 201  # the limit is per person


# ------------------------------------------------------------------ 4: the dashboard is not a minute behind
def test_the_dashboard_updates_at_once_after_a_change(work):
    before = work.admin.get("/dashboard").json()
    assert before["total_tasks"] >= 1
    work.admin.get("/dashboard")  # cached now
    assert work.mgr.delete(f"/tasks/{work.tasks['t3']['id']}").status_code == 204  # a task with 1 h logged on it
    after = work.admin.get("/dashboard").json()
    assert after["total_tasks"] == before["total_tasks"] - 1 and after["total_hours"] == before["total_hours"] - 1
    work.m2.post("/time-entries", {"task_id": work.tasks["t2"]["id"], "hours": 2})
    assert work.admin.get("/dashboard").json()["total_hours"] == after["total_hours"] + 2


# ------------------------------------------------------------------ 6: who may delete a task
def test_an_assignee_cannot_delete_a_task_somebody_else_created_for_them(work):
    mine = work.tasks["t1"]  # created by the manager, assigned to Mia
    assert detail(work.m1, mine)["can_edit"] is True and detail(work.m1, mine)["can_delete"] is False
    r = work.m1.delete(f"/tasks/{mine['id']}")
    assert r.status_code == 403 and "only the person who created it" in r.json()["message"]
    own = work.m1.post("/tasks", {"project_id": work.project["id"], "title": "Mine", "assignee_ids": [work.m1.user_id]}).json()
    assert detail(work.m1, own)["can_delete"] is True
    assert work.m1.delete(f"/tasks/{own['id']}").status_code == 204  # her own creation
    assert work.lead.delete(f"/tasks/{work.tasks['t2']['id']}").status_code == 204  # a team lead manages the team's tasks
    assert work.mgr.delete(f"/tasks/{mine['id']}").status_code == 204


# ------------------------------------------------------------------ 24: finished tasks last
def test_finished_tasks_come_last_in_the_list(work):
    items = work.m1.get("/tasks").json()["items"]
    statuses = [t["status"] for t in items]
    assert "done" in statuses and statuses.index("done") > max(i for i, s in enumerate(statuses) if s != "done")


# ------------------------------------------------------------------ 13: the reason is the real one
def test_a_backwards_date_range_says_so(work):
    r = work.admin.get("/reports/weekly", params={"from": "2026-11-11", "to": "2026-11-01"})
    assert r.status_code == 400 and r.json()["message"] == "The From date must be on or before the To date."
    r = work.admin.get("/reports/weekly", params={"from": "2024-01-01", "to": "2026-11-01"})
    assert r.json()["message"] == "Choose a range of at most 400 days."


# ------------------------------------------------------------------ 14: the assistant lists everything it counts
@pytest.fixture
def assistant_ready(work, owner_conn):
    grant_assistant_to_members(owner_conn)


def test_the_assistant_lists_every_upcoming_task_the_tool_returned(work, monkeypatch, assistant_ready):
    due = (work.today + dt.timedelta(days=1)).isoformat()
    work.mgr.post("/tasks", {"project_id": work.project["id"], "title": "Review deck", "assignee_ids": [work.m1.user_id], "due_date": due}).raise_for_status()
    # two open tasks are due soon (Build API, Review deck); the model asks for them and then names only one
    script(monkeypatch, [{"action": "tool", "tool": "get_upcoming", "args_json": "{\"days\": 30}"}, {"action": "answer", "sentences": ["“Build API” in Apollo is due in five days."]}])
    text = " ".join(sentences(ask(work.admin, message="Which open tasks are due soon?")))
    assert "Build API" in text and "Review deck" in text  # the one the model left out is added from the tool result


# ------------------------------------------------------------------ 11: the screen can say a validation error in plain words
def test_validation_errors_carry_the_rule_that_failed(work):
    r = work.m1.post("/time-entries", {"task_id": work.tasks["t4"]["id"], "hours": -5})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    d = r.json()["details"][0]
    assert d["loc"][-1] == "hours" and d["type"] == "greater_than" and d["ctx"] == {"gt": 0}
    r = work.mgr.post("/tasks", {"project_id": work.project["id"], "title": "x", "eta_hours": -1, "assignee_ids": [work.m1.user_id]})
    d = r.json()["details"][0]
    assert d["loc"][-1] == "eta_hours" and d["type"] == "greater_than_equal" and d["ctx"] == {"ge": 0}
    r = work.admin.post("/auth/forgot-password", {"email": "a@b.test"})  # a reserved domain: the failure is an e-mail rule, which the screen words simply
    assert r.status_code == 422 and r.json()["details"][0]["type"] == "value_error"


# ------------------------------------------------------------------ time keeps its minutes
def test_a_one_minute_timer_is_kept_as_one_minute(work, owner_conn):
    task = work.tasks["t4"]
    e = work.m1.post("/time-entries/start", {"task_id": task["id"]}).json()
    owner_conn.execute("UPDATE time_entries SET started_at = now() - interval '60 seconds' WHERE id = %s", (e["id"],))
    stopped = work.m1.post(f"/time-entries/{e['id']}/stop").json()
    assert stopped["hours"] == 0.0167 and round(stopped["hours"] * 60) == 1 and stopped["stopped_at"]  # was 0.02 h (1.2 minutes) with two decimals
    manual = work.m1.post("/time-entries", {"task_id": task["id"], "hours": 0.0833, "entry_date": (work.today - dt.timedelta(days=3)).isoformat()}).json()
    assert manual["hours"] == 0.0833  # 5 minutes
    assert work.m1.get(f"/tasks/{task['id']}").json()["actual_hours"] == pytest.approx(0.0167 + 0.0833, abs=1e-4)
