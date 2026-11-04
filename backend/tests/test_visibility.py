"""The project visibility report: figures computed in code, rendered as Markdown in the agreed layout, previewed as HTML with real
charts, downloadable as .md, and written up by the AI (sentences only) for client / internal templates."""

import datetime as dt
import json
import re

import pytest

from app.reports import mdreport, mermaid
from app.services import ai

from .conftest import drain, pdf_works
from .test_client_reports import enable_ai, make_template


def window(work):
    return {"from": (work.today - dt.timedelta(days=6)).isoformat(), "to": work.today.isoformat()}


def vis(api, **params):
    r = api.get("/reports/visibility", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def by_name(figures):
    return {p["name"]: p for p in figures["projects"]}


def make_owner(work, user):
    work.admin.put(f"/projects/{work.project['id']}/members", {"user_ids": [], "owner_ids": [user.user_id]}).raise_for_status()


def markdown_of(work, **fmt):
    r = work.mgr.post("/reports/visibility/export", {**window(work)}, params={"format": "md"})
    assert r.status_code == 202, r.text
    drain()
    run = work.mgr.get(f"/report-runs/{r.json()['id']}").json()
    assert run["status"] == "ready" and run["downloads"]["md"], run
    return work.client.get(run["downloads"]["md"]), run


# ------------------------------------------------------------------------------------------------ figures
def test_figures_per_project(work):
    make_owner(work, work.m1)
    f = vis(work.mgr, **window(work))["figures"]
    apollo, hermes = by_name(f)["Apollo"], by_name(f)["Hermes"]
    assert (apollo["planned"], apollo["completed"], apollo["in_progress"], apollo["pending"], apollo["progress"]) == (4, 1, 1, 2, 25)
    assert apollo["status"] == "in_progress" and apollo["client"] == "Globex"
    assert apollo["deliverables"] == ["Ship login"]
    assert {a["title"]: a["status"] for a in apollo["activities"]}["Build API"] == "in_progress"
    assert (hermes["planned"], hermes["in_progress"], hermes["progress"]) == (1, 1, 0)  # Fix pipeline is blocked = in flight
    assert apollo["owners"] == ["Mia Member"] and hermes["owners"] == []
    assert apollo["hours"] == 9.0 and sum(d["pct"] for d in apollo["work_distribution"]) == 100
    assert {x["name"]: x["hours"] for x in apollo["people"]} == {"Mia Member": 3.0, "Max Member": 2.0, "Olive Outsider": 4.0}
    assert f["totals"] == {"projects": 2, "planned": 5, "completed": 1, "in_progress": 2, "pending": 2, "hours": 10.0}
    assert sum(d["pct"] for d in f["team_distribution"]) == 100


def test_only_work_active_in_the_period_counts(work, owner_conn):
    owner_conn.execute("UPDATE tasks SET completed_at = now() - interval '40 days', created_at = now() - interval '45 days' WHERE title = 'Ship login'")
    f = vis(work.mgr, **window(work))["figures"]
    assert by_name(f)["Apollo"]["planned"] == 3 and by_name(f)["Apollo"]["completed"] == 0  # finished long before the period


def test_a_project_with_everything_done_is_completed(work):
    for t in ("t2", "t4", "t5"):
        work.mgr.patch(f"/tasks/{work.tasks[t]['id']}", {"status": "done"}).raise_for_status()
    apollo = by_name(vis(work.mgr, **window(work))["figures"])["Apollo"]
    assert apollo["status"] == "completed" and apollo["progress"] == 100 and apollo["pending"] == 0


def test_scope_and_permission(work):
    team = by_name(vis(work.lead, **window(work))["figures"])
    assert team["Apollo"]["planned"] == 3 and "Outside work" not in str(team)  # Olive's task is outside Leo's team
    assert work.m1.get("/reports/visibility").status_code == 403
    assert "visibility" in {r["key"] for r in work.admin.get("/reports").json()["items"]}


def test_client_figures_have_no_people(work):
    make_owner(work, work.m1)
    from app.db import session_scope
    from app.reports.base import ReportContext
    from app.reports.visibility import query

    cid = work.mgr.get("/me").json()["company"]["id"]
    with session_scope(cid) as db:
        f = query(ReportContext(db=db, start=work.today - dt.timedelta(days=6), end=work.today, today=work.today, include_people=False))
    assert "team_distribution" not in f
    assert all("owners" not in p and "people" not in p for p in f["projects"])


# ------------------------------------------------------------------------------------------------ markdown layout
def test_markdown_follows_the_agreed_layout(work):
    make_owner(work, work.m1)
    resp, _ = markdown_of(work)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"] if "content-disposition" in resp.headers else True
    md = resp.text
    for must in (
        "# 📊 Project Visibility Report — Apollo", "| **Owner** | Mia Member |", "| **Status** | 🟡 In Progress |", "# 🎯 Sprint Goal & Objectives",
        "> **Sprint Goal:** ", "| 🎯 Planned Tasks | ✅ Completed | 🚧 In Progress | 📅 Pending | 📊 Sprint Progress |",
        "| **4** | **1** | **1** | **2** | **25%** |", "# 📈 Sprint Dashboard", "## Sprint Status Distribution", "```mermaid",
        'pie title Sprint Progress Distribution\n    "Completed" : 1\n    "In Progress" : 1\n    "Pending" : 2', "# 🚀 Apollo Workflow", "flowchart LR",
        "## Current Activities", "| Ship login | ✅ Completed |", "| Build API | 🚧 In Progress |", "| Write docs | 📅 Pending |",
        "# ✅ Completed Deliverables", "| 1 | Ship login | ✅ |", "# 📈 Work Distribution", "pie title Work Distribution",
        "# 📊 Project Visibility Report — Hermes", "# 📊 Combined Sprint Health Dashboard", '"Apollo (25%)" : 25', "# 📊 Summary Dashboard",
        "| Project | Owner | Progress | Status | Key Achievement |", "# 📊 Team Work Distribution",
    ):
        assert must in md, must
    assert md.count("# 📊 Project Visibility Report —") == 2 and md.index("Hermes") < md.index("Combined Sprint Health")


def test_markdown_escapes_user_text(work):
    work.mgr.post("/tasks", {"project_id": work.project["id"], "title": "<script>alert(1)</script> | pipe & more", "assignee_ids": [work.m1.user_id]}).raise_for_status()
    md = markdown_of(work)[0].text
    assert "<script>" not in md and "&lt;script>alert(1)&lt;/script>" in md.replace("&lt;/script>", "&lt;/script>")
    assert "\\| pipe &amp; more" in md  # the table cell stays intact


def test_document_shape_helpers():
    assert mdreport.nice_period({"start": "2026-10-05", "end": "2026-10-19"}) == "05 Oct – 19 Oct 2026"
    assert mdreport.nice_period({"start": "2026-12-28", "end": "2027-01-03"}) == "28 Dec 2026 – 03 Jan 2027"
    assert mdreport.label('He said "hi" [x] (y)') == "He said hi x y"
    assert mdreport.esc("a|b\nc<d") == "a\\|b c&lt;d"


def test_empty_period_renders_a_note(work):
    md = mdreport.visibility_markdown({"period": {"start": "2026-01-05", "end": "2026-01-11"}, "projects": []}, "Project visibility report", "Acme")
    assert "No project activity between 05 Jan – 11 Jan 2026" in md


# ------------------------------------------------------------------------------------------------ html / charts
def test_preview_html_has_real_charts_not_mermaid_source(work):
    html = vis(work.mgr, **window(work))["html"]
    assert "<svg" in html and 'class="chart flow"' in html and "language-mermaid" not in html and "```" not in html
    assert "Project Visibility Report" in html and "Combined Sprint Health Dashboard" in html


def test_mermaid_converter():
    pie = mermaid.to_html('pie title Work <b>\n    "Dev" : 30\n    "QA" : 70')
    assert pie and pie.count("<path") == 2 and "&lt;b&gt;" in pie and "70%" in pie
    assert "<circle" in mermaid.to_html('pie title One\n    "Only" : 5')  # a single slice is a full circle
    flow = mermaid.to_html("flowchart LR\n\nA[Design]\n-->B[Build]\n\nB-->C[Ship]")
    assert flow.count('class="node"') == 3 and flow.count("→") == 2
    assert mermaid.to_html('pie title Empty\n    "x" : 0') is None and mermaid.to_html("sequenceDiagram\nA->>B: hi") is None
    html = '<p>x</p><pre><code class="language-mermaid">sequenceDiagram\nA-&gt;&gt;B</code></pre>'
    assert mermaid.replace_blocks(html) == html  # unknown diagrams stay as code


# ------------------------------------------------------------------------------------------------ exports
def test_every_export_format_works_for_the_visibility_report(work):
    ids = {}
    for fmt in ("xlsx", "docx", "md"):
        ids[fmt] = work.mgr.post("/reports/visibility/export", {**window(work)}, params={"format": fmt}).json()["id"]
    drain()
    for fmt, rid in ids.items():
        run = work.mgr.get(f"/report-runs/{rid}").json()
        assert run["status"] == "ready" and run["downloads"][fmt], (fmt, run)
        assert work.client.get(run["downloads"][fmt]).status_code == 200


def test_markdown_endpoint_for_runs_and_access(work):
    run_id = work.lead.post("/reports/weekly/export", {}, params={"format": "md"}).json()["id"]
    drain()
    assert work.lead.get(f"/report-runs/{run_id}").json()["downloads"]["md"]
    r = work.lead.get(f"/report-runs/{run_id}/markdown")
    assert r.status_code == 200 and "# Weekly report" in r.text and "| **Reporting Period** |" in r.text and "## Projects" in r.text
    assert 'filename="Weekly-report-' in r.headers["content-disposition"]
    assert work.m1.get(f"/report-runs/{run_id}/markdown").status_code == 403  # private to the requester
    assert work.mgr.get(f"/report-runs/{run_id}/markdown").status_code == 403
    assert work.lead.get("/reports/weekly/export", params={"format": "md"}).status_code in (404, 405)


def test_unknown_export_format_is_rejected(work):
    assert work.mgr.post("/reports/visibility/export", {}, params={"format": "html"}).status_code == 400


# ------------------------------------------------------------------------------------------------ AI drafting
REPLY = {
    "projects": {"Apollo": {"sprint_goal": "Ship the Apollo login and API foundations.", "workflow": ["Design", "Build API", "Test", "Release"],
                            "key_achievement": "Login shipped on schedule"}},
    "questions": [],
}


def generate(work, tpl, **body):
    r = work.mgr.post(f"/report-templates/{tpl['id']}/generate", {**window(work), **body})
    assert r.status_code == 202, r.text
    drain()
    return work.mgr.get(f"/report-runs/{r.json()['id']}").json()


def test_client_template_without_ai_uses_the_figures_fallback(work):
    t = make_template(work, base_report="visibility", sections=[], name="Globex visibility")
    assert t["sections"] == ["Sprint goal", "Workflow", "Key achievement"]
    run = generate(work, t)
    assert run["status"] == "drafted" and run["ai_provider"] == "figures_only"
    assert run["sections"] == ["Sprint goal — Apollo", "Workflow — Apollo", "Key achievement — Apollo"]  # one set per project of the client
    assert run["ai_text"]["Sprint goal — Apollo"].startswith("Deliver the 4 planned tasks for Apollo")
    assert "→" in run["ai_text"]["Workflow — Apollo"]
    f = run["figures"]
    assert [p["name"] for p in f["projects"]] == ["Apollo"] and "owners" not in f["projects"][0] and "team_distribution" not in f
    assert "Mia" not in json.dumps(f) and "Hermes" not in json.dumps(f)


def test_ai_writes_only_the_sentences_and_never_sees_names(work, monkeypatch):
    make_owner(work, work.m1)
    calls = []
    enable_ai(monkeypatch, reply=json.dumps(REPLY), record=calls)
    internal = make_template(work, base_report="visibility", sections=[], audience="internal", client_id=None, name="Internal visibility")
    run = generate(work, internal)
    assert run["ai_provider"] == "anthropic" and run["ai_text"]["Sprint goal — Apollo"] == "Ship the Apollo login and API foundations."
    assert run["ai_text"]["Workflow — Apollo"] == "Design → Build API → Test → Release"
    system, user = calls[0]
    assert "Project Visibility Report" in system and "Never mention people" in system
    for forbidden in ("Mia", "Max", "Olive", "Leo", "Maya", "owners", "team_distribution", "people", "acme.com"):
        assert forbidden not in user, forbidden
    assert "Ship login" in user and "Apollo" in user and "work_distribution" in user
    # the internal report still names the owner, outside the model call
    md = work.mgr.get(f"/report-runs/{run['id']}/markdown").text
    assert "| **Owner** | Mia Member |" in md and "> **Sprint Goal:** Ship the Apollo login and API foundations." in md
    assert "Design" in md and "A[Design]" in md and "-->B[Build API]" in md


def test_incomplete_model_output_is_flagged_and_filled_from_figures(work, monkeypatch):
    enable_ai(monkeypatch, reply=json.dumps({"projects": {"Apollo": {"sprint_goal": "Only a goal."}}, "questions": ["Which release is this?"]}))
    run = generate(work, make_template(work, base_report="visibility", sections=[], name="V"))
    assert run["ai_text"]["Sprint goal — Apollo"] == "Only a goal."
    assert run["ai_text"]["Workflow — Apollo"] and run["ai_text"]["Key achievement — Apollo"]
    qs = run["ai_text"]["_questions"]
    assert "Which release is this?" in qs and any("Apollo" in q for q in qs)
    with pytest.raises(ValueError):
        ai.parse_visibility_output("no json", {"projects": []})


def test_edit_redraft_and_markdown_stay_in_sync(work, monkeypatch):
    calls = []
    enable_ai(monkeypatch, reply=json.dumps(REPLY), record=calls)
    run = generate(work, make_template(work, base_report="visibility", sections=[], name="V"))
    edited = work.mgr.patch(f"/report-runs/{run['id']}", {"ai_text": {"Sprint goal — Apollo": "A human wrote this goal."}})
    assert edited.status_code == 200
    assert work.mgr.patch(f"/report-runs/{run['id']}", {"ai_text": {"Sprint goal — Nope": "x"}}).status_code == 400
    assert "> **Sprint Goal:** A human wrote this goal." in work.mgr.get(f"/report-runs/{run['id']}/markdown").text
    assert "A human wrote this goal." in work.mgr.get(f"/report-runs/{run['id']}/preview").json()["html"]
    work.mgr.post(f"/report-runs/{run['id']}/redraft", {"note": "shorter"}).raise_for_status()
    drain()
    assert len(calls) == 2 and "shorter" in calls[1][1] and "PREVIOUS DRAFT" in calls[1][1]


@pytest.mark.skipif(not pdf_works(), reason="Chromium not available")
def test_approve_share_and_download_markdown_from_the_client_page(work, monkeypatch):
    enable_ai(monkeypatch, reply=json.dumps(REPLY))
    run = generate(work, make_template(work, base_report="visibility", sections=[], name="Globex visibility"))
    work.mgr.post(f"/report-runs/{run['id']}/approve").raise_for_status()
    drain()
    done = work.mgr.get(f"/report-runs/{run['id']}").json()
    assert all(done["downloads"][f] for f in ("pdf", "docx", "xlsx", "md"))
    md = work.client.get(done["downloads"]["md"]).text
    assert "# 📊 Project Visibility Report — Apollo" in md and "| **Owner**" not in md  # client copy: no people
    assert "Team Work Distribution" not in md and "Mia" not in md
    contact = work.mgr.get(f"/clients/{work.globex['id']}/contacts").json()["items"][0]["id"]
    work.mgr.post(f"/report-runs/{run['id']}/share", {"contact_ids": [contact]}).raise_for_status()
    drain()
    from app.services import mail

    token = next(m for m in mail.outbox if m["to"] == "gina@globex.com")["text"].split("/shared/")[1].split()[0]
    page = work.client.get(f"/api/v1/shared/{token}").json()
    assert page["markdown_url"].endswith("/markdown") and "<svg" in page["html"]
    shared_md = work.client.get(page["markdown_url"])
    assert shared_md.status_code == 200 and shared_md.text == md and "attachment" in shared_md.headers["content-disposition"]
    assert work.client.get("/api/v1/shared/not-a-token/markdown").status_code == 404


def test_visibility_is_not_allowed_to_leak_names_to_a_client_via_sanitiser():
    figures = {"projects": [{"name": "P", "owners": ["Ann"], "people": [{"name": "Ann"}], "planned": 1, "activities": [], "deliverables": [],
                             "work_distribution": [], "completed": 0, "in_progress": 0, "pending": 1}], "team_distribution": [{"label": "Ann - P"}]}
    prompt = ai.build_visibility_prompt(figures, {"name": "T"}, None, None)
    assert "Ann" not in prompt and "owners" not in prompt


def test_section_names_roundtrip_through_the_markdown_keys():
    p = {"name": "Schedulator — v2", "planned": 1, "completed": 0, "in_progress": 1, "pending": 0, "progress": 0, "status": "in_progress",
         "activities": [{"title": "T", "status": "in_progress"}], "deliverables": [], "work_distribution": []}
    text = {mdreport.key("Sprint goal", p["name"]): "Goal.", mdreport.key("Workflow", p["name"]): "A → B -> C", mdreport.key("Key achievement", p["name"]): "Done."}
    goal, stages, ach = mdreport.narrative(p, text)
    assert (goal, stages, ach) == ("Goal.", ["A", "B", "C"], "Done.")
    assert re.search(r"^> \*\*Sprint Goal:\*\* Goal\.$", mdreport.visibility_markdown({"period": {"start": "2026-10-05", "end": "2026-10-19"}, "projects": [p]}, "t", "c", text), re.M)


def test_report_tabs_have_a_stable_logical_order(work):
    assert [r["key"] for r in work.mgr.get("/reports").json()["items"]] == ["weekly", "monthly", "performance", "visibility"]
