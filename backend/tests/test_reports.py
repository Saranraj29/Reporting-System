import io

import pytest

from .conftest import drain, pdf_works


def figures(api, key="weekly", **params):
    r = api.get(f"/reports/{key}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def window(work):
    import datetime as dt

    return {"from": (work.today - dt.timedelta(days=6)).isoformat(), "to": work.today.isoformat()}


def test_weekly_figures(work):
    j = figures(work.mgr, **window(work))
    f = j["figures"]
    assert f["totals"] == {"hours": 10.0, "tasks_completed": 1, "tasks_created": 5, "tasks_open": 4, "blocked_tasks": 1, "overdue_tasks": 1}
    proj = {p["project"]: p for p in f["projects"]}
    assert proj["Apollo"]["hours"] == 9.0 and proj["Apollo"]["client"] == "Globex" and proj["Hermes"]["hours"] == 1.0
    assert [t["title"] for t in f["completed_tasks"]] == ["Ship login"]
    assert [b["title"] for b in f["blockers"]] == ["Fix pipeline"]
    assert f["overdue"][0]["title"] == "Write docs" and f["overdue"][0]["days_late"] >= 3
    people = {p["name"]: p["hours"] for p in f["people"]}
    assert people["Mia Member"] == 4.0 and people["Olive Outsider"] == 4.0
    assert "Apollo" in j["html"] and "Weekly report" in j["html"]


def test_weekly_report_respects_team_scope(work):
    f = figures(work.lead, **window(work))["figures"]
    assert f["totals"]["hours"] == 6.0  # Mia + Max only
    assert {p["name"] for p in f["people"]} == {"Mia Member", "Max Member"}
    assert "Outside work" not in str(f)


def test_user_filter_cannot_escape_scope(work):
    f = figures(work.lead, user=work.out.user_id, **window(work))["figures"]
    assert f["totals"]["hours"] == 0


def test_monthly_has_comparison_and_weeks(work):
    j = figures(work.mgr, "monthly", **window(work))
    f = j["figures"]
    assert f["comparison"]["hours_previous"] == 0 and f["comparison"]["hours_change"] == 10.0
    assert sum(w["hours"] for w in f["weeks"]) == 10.0 and len(f["weeks"]) >= 1
    assert "Week by week" in j["html"]


def test_performance_report_is_per_person(work):
    f = figures(work.lead, "performance", **window(work))["figures"]
    rows = {p["name"]: p for p in f["people"]}
    assert set(rows) >= {"Mia Member", "Max Member"} and "Olive Outsider" not in rows
    mia = rows["Mia Member"]
    assert mia["hours"] == 4.0 and mia["tasks_completed"] == 1 and mia["on_time_rate"] == 100
    assert mia["blocked_tasks"] == 1 and mia["open_tasks"] == 2
    assert work.m1.get("/reports/performance").status_code == 403
    assert work.admin.get("/reports/performance").status_code == 403


def test_report_validation(work):
    assert work.mgr.get("/reports/nope").status_code == 404
    assert work.mgr.get("/reports/weekly", params={"from": "2026-03-10", "to": "2026-03-01"}).status_code == 400
    assert work.mgr.post("/reports/weekly/export", params={"format": "gif"}).status_code == 400
    assert work.m1.post("/reports/weekly/export", params={"format": "pdf"}).status_code == 403


def _download(api, url):
    r = api.c.get(url)
    assert r.status_code == 200, r.text
    return r.content


def test_export_xlsx_through_the_worker(work):
    r = work.lead.post("/reports/weekly/export", {**{"from": window(work)["from"], "to": window(work)["to"]}}, params={"format": "xlsx"})
    assert r.status_code == 202
    run_id = r.json()["id"]
    assert work.lead.get(f"/report-runs/{run_id}").json()["status"] == "queued"
    assert drain() >= 1
    run = work.lead.get(f"/report-runs/{run_id}").json()
    assert run["status"] == "ready" and run["downloads"]["xlsx"]
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(_download(work.lead, run["downloads"]["xlsx"])))
    assert {"Summary", "Projects", "People"} <= set(wb.sheetnames)
    names = [row[0].value for row in wb["People"].iter_rows(min_row=2)]
    assert "Olive Outsider" not in names and "Mia Member" in names  # export honours the requester's scope
    # the requester is told when it is ready
    from app.services import mail

    assert any("Report ready" in m["subject"] and m["to"] == "leo.lead@acme.com" for m in mail.outbox)


def test_export_docx_through_the_worker(work):
    run_id = work.mgr.post("/reports/monthly/export", {}, params={"format": "docx"}).json()["id"]
    drain()
    run = work.mgr.get(f"/report-runs/{run_id}").json()
    from docx import Document

    doc = Document(io.BytesIO(_download(work.mgr, run["downloads"]["docx"])))
    assert "Monthly report" in doc.paragraphs[0].text


@pytest.mark.skipif(not pdf_works(), reason="Chromium not available")
def test_export_pdf_through_the_worker(work):
    run_id = work.mgr.post("/reports/weekly/export", {}, params={"format": "pdf"}).json()["id"]
    drain()
    run = work.mgr.get(f"/report-runs/{run_id}").json()
    assert run["status"] == "ready"
    assert _download(work.mgr, run["downloads"]["pdf"]).startswith(b"%PDF")


def test_runs_are_private_to_requester_and_download_links_are_signed(work):
    run_id = work.lead.post("/reports/weekly/export", {}, params={"format": "xlsx"}).json()["id"]
    drain()
    assert work.m1.get(f"/report-runs/{run_id}").status_code == 403
    assert work.mgr.get(f"/report-runs/{run_id}").status_code == 403  # no client-report permission => no peeking at others' exports
    assert work.lead.get("/report-runs").json()["total"] == 1
    assert work.m1.get("/report-runs").json()["total"] == 0
    url = work.lead.get(f"/report-runs/{run_id}").json()["downloads"]["xlsx"]
    assert work.client.get(url[:-3] + "abc").status_code == 404  # tampered token
    assert work.client.get(url).status_code == 200


def test_failed_export_is_marked_failed_after_three_attempts(work, monkeypatch, owner_conn):
    from app.services import exporters

    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(exporters, "to_xlsx", boom)
    run_id = work.mgr.post("/reports/weekly/export", {}, params={"format": "xlsx"}).json()["id"]
    drain()  # backoff is 0 in tests, so retries run immediately
    job = owner_conn.execute("SELECT status, attempts FROM jobs WHERE kind = 'report.generate'").fetchone()
    assert job == ("failed", 3)
    run = work.mgr.get(f"/report-runs/{run_id}").json()
    assert run["status"] == "failed" and "disk on fire" in run["error"]
    from app.services import mail

    assert any("Report failed" in m["subject"] for m in mail.outbox)  # the requester is told


def test_new_reports_are_plugins():
    """Adding a report = one module + register(); nothing else in the app is touched."""
    from app.reports import REGISTRY
    from app.reports.base import ReportDef, register

    d = register(ReportDef(key="demo", title="Demo", required_permission="report.weekly.view", query=lambda rc: {"period": {}},
                           template="weekly.html", default_period=lambda t: (t, t)))
    assert REGISTRY["demo"] is d
    del REGISTRY["demo"]
