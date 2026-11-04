"""GitLab-style issue panel: Testing status, activity feed with system notes, markdown comments, internal notes."""


def mk(api, project_id, title="T", **kw):
    r = api.post("/tasks", {"project_id": project_id, "title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def feed(api, task_id):
    r = api.get(f"/tasks/{task_id}/comments")
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_testing_status_and_validation(org):
    o = org
    t = mk(o.m1, o.project["id"], "QA me")
    r = o.m1.patch(f"/tasks/{t['id']}", {"status": "testing"})
    assert r.status_code == 200 and r.json()["status"] == "testing" and not r.json()["is_blocked"]
    assert o.m1.get("/tasks", params={"status": "testing"}).json()["total"] == 1
    assert o.m1.patch(f"/tasks/{t['id']}", {"status": "qa"}).status_code == 422
    assert o.mgr.get("/dashboard").json()["tasks_by_status"]["testing"] == 1
    done = o.m1.patch(f"/tasks/{t['id']}", {"status": "done"}).json()
    assert done["completed_at"]  # testing -> done completes the task as usual


def test_activity_feed_gets_system_notes(org):
    o = org
    t = mk(o.lead, o.project["id"], "Feature", assignee_ids=[o.m1.user_id])
    o.m1.patch(f"/tasks/{t['id']}", {"status": "in_progress"})
    o.m1.patch(f"/tasks/{t['id']}", {"status": "testing", "priority": "high", "due_date": "2030-01-15"})
    o.m1.post("/time-entries", {"task_id": t["id"], "hours": 2, "note": "pairing"})
    o.lead.put(f"/tasks/{t['id']}/assignees", {"user_ids": [o.m1.user_id, o.m2.user_id]})
    o.m1.post(f"/tasks/{t['id']}/comments", {"body": "Ready for QA"})
    notes = [(c["kind"], c["body"]) for c in feed(o.lead, t["id"])]
    assert notes[0] == ("system", "created this task")
    bodies = [b for _, b in notes]
    assert "changed status from **To do** to **In progress**" in bodies
    assert "changed status from **In progress** to **Testing**" in bodies
    assert "changed priority from **medium** to **high**" in bodies
    assert "changed the due date to **2030-01-15**" in bodies
    assert "logged **2h** — pairing" in bodies
    assert any(b.startswith("set the assignees to **Max Member, Mia Member**") for b in bodies)
    assert notes[-1] == ("comment", "Ready for QA")
    assert not any(k == "system" and "status" in b for k, b in notes[:1])  # creating with the default status writes no status note


def test_timer_writes_a_system_note(org, owner_conn):
    o = org
    t = mk(o.m1, o.project["id"], "Timed")
    e = o.m1.post("/time-entries/start", {"task_id": t["id"]}).json()
    owner_conn.execute("UPDATE time_entries SET started_at = now() - interval '90 minutes' WHERE id = %s", (e["id"],))
    o.m1.post(f"/time-entries/{e['id']}/stop").raise_for_status()
    assert "tracked **1.5h** with the timer" in [c["body"] for c in feed(o.m1, t["id"])]


def test_markdown_comments_are_stored_verbatim(org):
    o = org
    t = mk(o.m1, o.project["id"], "Docs")
    body = "**bold** _it_ ~~gone~~\n> quote\n- [ ] todo\n- [x] done\n```py\nprint('x')\n```\n[link](https://example.com)"
    c = o.m1.post(f"/tasks/{t['id']}/comments", {"body": body})
    assert c.status_code == 201 and c.json()["body"] == body and c.json()["kind"] == "comment" and c.json()["is_internal"] is False
    assert o.m1.post(f"/tasks/{t['id']}/comments", {"body": "   "}).status_code in (201, 422)  # whitespace is trimmed by the API
    assert o.m1.post(f"/tasks/{t['id']}/comments", {"body": "x" * 10001}).status_code == 422


def test_internal_notes_are_hidden_from_people_who_only_see_their_own_work(org):
    o = org
    t = mk(o.lead, o.project["id"], "Shared", assignee_ids=[o.m1.user_id, o.m2.user_id])
    o.lead.post(f"/tasks/{t['id']}/comments", {"body": "visible to all assignees"})
    o.lead.post(f"/tasks/{t['id']}/comments", {"body": "lead-only: watch the budget", "is_internal": True})
    o.m1.post(f"/tasks/{t['id']}/comments", {"body": "my own private note", "is_internal": True})
    texts = lambda api: {c["body"] for c in feed(api, t["id"]) if c["kind"] == "comment"}  # noqa: E731
    assert texts(o.lead) == {"visible to all assignees", "lead-only: watch the budget", "my own private note"}  # team scope sees internal
    assert texts(o.mgr) == texts(o.lead)
    assert texts(o.m1) == {"visible to all assignees", "my own private note"}  # own scope: only their own internal note
    assert texts(o.m2) == {"visible to all assignees"}
    internal = [c for c in feed(o.lead, t["id"]) if c["is_internal"]]
    assert len(internal) == 2


def test_project_owner_sees_internal_notes(org):
    o = org
    t = mk(o.lead, o.project["id"], "Owned", assignee_ids=[o.m2.user_id])
    o.lead.post(f"/tasks/{t['id']}/comments", {"body": "internal for owners", "is_internal": True})
    o.admin.put(f"/projects/{o.project['id']}/members", {"user_ids": [], "owner_ids": [o.m1.user_id]})
    assert "internal for owners" in {c["body"] for c in feed(o.m1, t["id"])}
    assert "internal for owners" not in {c["body"] for c in feed(o.m2, t["id"])}


def test_comments_need_task_visibility(org):
    o = org
    t = mk(o.m1, o.project["id"], "Private")
    assert o.out.get(f"/tasks/{t['id']}/comments").status_code == 404
    assert o.out.post(f"/tasks/{t['id']}/comments", {"body": "hi"}).status_code == 404
