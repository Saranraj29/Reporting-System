"""Morning plan + end-of-day update, tracked per person and visible in the summary, dashboard, reports and reminders."""

import datetime as dt
import io

from app.services import ai, mail
from app.services.dashboard import clear_dashboard_cache
from app.worker import schedule_tick

from .conftest import drain

TODAY = dt.date.today


def put(api, **fields):
    r = api.put(f"/daily-status/{TODAY()}", {**fields})
    assert r.status_code == 200, r.text
    return r.json()


def test_morning_and_eod_are_timestamped_separately(org):
    o = org
    a = put(o.m1, plan_today="Finish the login page")
    assert a["morning_at"] and a["eod_at"] is None and a["plan_today"] == "Finish the login page"
    b = put(o.m1, plan_today="Finish the login page", did_today="Login page done", next_up="Tests", blockers="")
    assert b["id"] == a["id"] and b["eod_at"] and b["morning_at"] == a["morning_at"]  # the morning stamp is kept
    c = put(o.m1, plan_today="Edited plan", did_today="Edited done")
    assert c["morning_at"] == a["morning_at"] and c["eod_at"] == b["eod_at"]  # editing does not re-stamp
    assert put(o.m2, did_today="only an EOD")["morning_at"] is None  # either check-in can be posted alone
    items = o.m1.get("/daily-status").json()["items"]
    assert len(items) == 1 and items[0]["plan_today"] == "Edited plan"


def test_summary_shows_who_is_missing_within_scope(org):
    o = org
    put(o.m1, plan_today="plan", did_today="done", blockers="waiting for the API key")
    put(o.m2, plan_today="plan only")
    s = o.lead.get("/daily-status/summary").json()  # Leo leads Core: Leo, Mia, Max
    assert s["expected"] == 3 and s["morning_done"] == 2 and s["eod_done"] == 1
    assert s["missing_morning"] == ["Leo Lead"] and sorted(s["missing_eod"]) == ["Leo Lead", "Max Member"]
    assert s["blockers"] == [{"user": "Mia Member", "text": "waiting for the API key"}]
    assert o.mgr.get("/daily-status/summary").json()["expected"] == 6
    me_only = o.m1.get("/daily-status/summary").json()
    assert me_only["expected"] == 1 and me_only["missing_morning"] == []


def test_dashboard_tracks_both_check_ins(org):
    o = org
    put(o.m1, plan_today="p", did_today="d")
    put(o.m2, plan_today="p")
    clear_dashboard_cache()
    d = o.mgr.get("/dashboard").json()["daily_status"]
    assert (d["expected"], d["morning_today"], d["eod_today"]) == (6, 2, 1)
    assert "Mia Member" not in d["missing_morning"] and "Max Member" in d["missing_eod"]
    team = o.lead.get("/dashboard").json()["daily_status"]
    assert team["expected"] == 3 and team["missing_morning"] == ["Leo Lead"]


def _window():
    t = TODAY()
    return {"from": (t - dt.timedelta(days=6)).isoformat(), "to": t.isoformat()}


def test_weekly_report_includes_check_in_tracking(work):
    put(work.m1, plan_today="Ship the login page", did_today="Shipped it", next_up="Docs", blockers="needs review")
    put(work.m2, plan_today="API work")
    j = work.mgr.get("/reports/weekly", params=_window()).json()
    f = j["figures"]
    rows = {c["name"]: c for c in f["check_ins"]}
    assert rows["Mia Member"]["morning_plans"] == 1 and rows["Mia Member"]["eod_updates"] == 1 and rows["Mia Member"]["days_with_blockers"] == 1
    assert rows["Max Member"]["eod_updates"] == 0 and rows["Max Member"]["working_days"] >= 1
    assert f["check_in_totals"]["people"] == 6 and f["check_in_totals"]["morning_plans"] == 2
    entry = next(e for e in f["check_in_entries"] if e["name"] == "Mia Member")
    assert entry["morning_plan"] == "Ship the login page" and entry["done"] == "Shipped it" and entry["morning_at"]
    assert "Daily check-ins" in j["html"] and "Ship the login page" in j["html"]


def test_report_check_ins_follow_the_report_scope(work):
    put(work.m1, plan_today="team member plan")
    put(work.out, plan_today="outsider plan")
    f = work.lead.get("/reports/weekly", params=_window()).json()["figures"]
    assert {c["name"] for c in f["check_ins"]} == {"Leo Lead", "Mia Member", "Max Member"}
    assert "outsider plan" not in str(f)


def test_check_in_export_has_its_own_sheets(work):
    put(work.m1, plan_today="plan A", did_today="did A")
    r = work.mgr.post("/reports/weekly/export", {**_window()}, params={"format": "xlsx"})
    drain()
    run = work.mgr.get(f"/report-runs/{r.json()['id']}").json()
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(work.client.get(run["downloads"]["xlsx"]).content))
    assert {"Check ins", "Check in entries"} <= set(wb.sheetnames)
    texts = [c.value for row in wb["Check in entries"].iter_rows(min_row=2) for c in row]
    assert "plan A" in texts


def test_check_in_text_never_reaches_client_reports_or_the_llm(work):
    put(work.m1, plan_today="SECRET morning plan", did_today="SECRET eod", blockers="SECRET blocker")
    figures = work.mgr.get("/reports/weekly", params=_window()).json()["figures"]
    assert "check_ins" in figures
    clean = ai.sanitize_figures(figures)
    assert not {"check_ins", "check_in_entries", "check_in_totals", "people"} & set(clean)
    assert "SECRET" not in str(clean)
    # a client report is built without people, hence without check-ins at all
    from .test_client_reports import make_template, window

    t = make_template(work)
    r = work.mgr.post(f"/report-templates/{t['id']}/generate", window(work))
    drain()
    run = work.mgr.get(f"/report-runs/{r.json()['id']}").json()
    assert "check_ins" not in run["figures"] and "SECRET" not in str(run["figures"]) + str(run["ai_text"])


def test_morning_reminder_goes_only_to_people_without_a_plan(work):
    put(work.m1, plan_today="plan")
    mail.outbox.clear()
    monday_10_05 = dt.datetime(2026, 11, 2, 10, 5, tzinfo=dt.UTC)
    schedule_tick(monday_10_05)
    # the reminder job checks the date in its payload; point it at today so it sees Mia's plan
    from app.db import session_scope
    from app.services import jobs

    with session_scope() as db:
        db.execute(__import__("sqlalchemy").text("DELETE FROM jobs WHERE kind = 'cron.morning_plan'"))
    cid = work.mgr.get("/me").json()["company"]["id"]
    with session_scope(cid) as db:
        jobs.enqueue(db, "cron.morning_plan", cid, {"date": TODAY().isoformat()})
    drain()
    reminded = {m["to"] for m in mail.outbox if "plan for today" in m["subject"]}
    assert "mia.member@acme.com" not in reminded and "max.member@acme.com" in reminded and "leo.lead@acme.com" in reminded


def test_morning_job_is_scheduled_for_weekdays_from_ten(org, owner_conn):
    before = dt.datetime(2026, 11, 2, 9, 30, tzinfo=dt.UTC)
    schedule_tick(before)
    assert owner_conn.execute("SELECT count(*) FROM jobs WHERE kind = 'cron.morning_plan'").fetchone()[0] == 0
    schedule_tick(dt.datetime(2026, 11, 2, 10, 1, tzinfo=dt.UTC))
    schedule_tick(dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.UTC))  # same day: deduped
    assert owner_conn.execute("SELECT count(*) FROM jobs WHERE kind = 'cron.morning_plan'").fetchone()[0] == 1
    schedule_tick(dt.datetime(2026, 11, 7, 11, 0, tzinfo=dt.UTC))  # Saturday
    assert owner_conn.execute("SELECT count(*) FROM jobs WHERE kind = 'cron.morning_plan'").fetchone()[0] == 1
