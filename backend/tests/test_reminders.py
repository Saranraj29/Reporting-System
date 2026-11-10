"""Reminder settings (company switch + send times) and time off (company holidays, personal leave)."""

import datetime as dt

from app.db import session_scope
from app.services import jobs, mail
from app.worker import schedule_tick

from .conftest import drain

MONDAY = dt.datetime(2026, 11, 2, 0, 0, tzinfo=dt.UTC)
REMINDER_SUBJECTS = {"Share your plan for today", "Please post your end-of-day update", "Tasks due soon or overdue", "Overdue tasks in your team"}


def at(hour, minute=0):
    return MONDAY.replace(hour=hour, minute=minute)


def queued(owner_conn):
    return sorted(r[0] for r in owner_conn.execute("SELECT kind FROM jobs WHERE kind LIKE 'cron.%' AND kind <> 'cron.ai_retention'"))


def run_reminder(owner_conn, kind, day):
    cid = owner_conn.execute("SELECT id FROM companies").fetchone()[0]
    with session_scope(cid) as db:
        jobs.enqueue(db, kind, cid, {"date": day.isoformat()})
    mail.outbox.clear()
    drain()  # also sends whatever the fixtures queued (blocker alerts...), so keep only the reminders
    return {m["to"] for m in mail.outbox if m["subject"] in REMINDER_SUBJECTS}


# ------------------------------------------------------------------ settings
def test_reminder_settings_default_to_the_old_hard_coded_times_and_can_be_changed(org):
    s = org.admin.get("/settings").json()
    assert (s["reminders_enabled"], s["reminder_morning_time"], s["reminder_eod_time"], s["reminder_due_time"]) == (True, "10:00", "17:30", "09:00")
    r = org.admin.patch("/settings", {"reminder_morning_time": "08:15", "reminder_eod_time": "16:45", "reminder_due_time": "07:30", "reminders_enabled": False}).json()
    assert (r["reminders_enabled"], r["reminder_morning_time"], r["reminder_eod_time"], r["reminder_due_time"]) == (False, "08:15", "16:45", "07:30")
    assert org.m1.get("/settings").json()["reminder_eod_time"] == "16:45"  # everyone reads them, only admins change them


def test_reminder_settings_are_validated_and_admin_only(org):
    assert org.admin.patch("/settings", {"reminder_morning_time": "25:00"}).status_code == 422
    assert org.admin.patch("/settings", {"reminder_morning_time": "9am"}).status_code == 422
    assert org.admin.patch("/settings", {"reminder_morning_time": "18:00"}).json()["code"] == "invalid_reminder_times"  # not before the 17:30 end-of-day time
    assert org.admin.patch("/settings", {"reminder_eod_time": "09:30"}).json()["code"] == "invalid_reminder_times"  # not after the 10:00 morning time
    assert org.admin.get("/settings").json()["reminder_morning_time"] == "10:00"  # a refused change changes nothing
    assert org.m1.patch("/settings", {"reminders_enabled": False}).status_code == 403


# ------------------------------------------------------------------ the worker follows the settings
def test_schedule_tick_uses_the_company_times(org, owner_conn):
    org.admin.patch("/settings", {"timezone": "UTC", "reminder_morning_time": "08:00", "reminder_eod_time": "16:00", "reminder_due_time": "07:30", "report_email_enabled": False}).raise_for_status()
    schedule_tick(at(7, 20))
    assert queued(owner_conn) == []
    schedule_tick(at(7, 40))
    assert queued(owner_conn) == ["cron.due"]
    schedule_tick(at(8, 5))
    assert queued(owner_conn) == ["cron.due", "cron.morning_plan"]
    schedule_tick(at(16, 5))
    assert queued(owner_conn) == ["cron.daily_missing", "cron.due", "cron.morning_plan"]


def test_company_switch_stops_reminders_but_not_report_emails(org, owner_conn):
    org.admin.patch("/settings", {"timezone": "UTC", "reminders_enabled": False, "report_email_enabled": True, "report_email_day": 0}).raise_for_status()
    schedule_tick(at(18, 0))  # Monday evening: every reminder time has passed
    assert queued(owner_conn) == ["cron.report_email"]
    org.admin.patch("/settings", {"reminders_enabled": True}).raise_for_status()
    schedule_tick(at(18, 5))  # switching it back on catches up the same day
    assert queued(owner_conn) == ["cron.daily_missing", "cron.due", "cron.morning_plan", "cron.report_email"]


def test_a_reminder_queued_before_the_switch_is_dropped(work, owner_conn):
    work.admin.patch("/settings", {"reminders_enabled": False}).raise_for_status()
    assert run_reminder(owner_conn, "cron.daily_missing", work.today) == set()


# ------------------------------------------------------------------ holidays
def test_nobody_is_reminded_on_a_company_holiday(work, owner_conn):
    h = work.admin.post("/holidays", {"start_date": work.today.isoformat(), "end_date": work.today.isoformat(), "note": "Founders day"})
    assert h.status_code == 201 and h.json()["note"] == "Founders day"
    for kind in ("cron.morning_plan", "cron.daily_missing", "cron.due"):
        assert run_reminder(owner_conn, kind, work.today) == set(), kind
    # the day after is a normal day again
    assert run_reminder(owner_conn, "cron.daily_missing", work.today + dt.timedelta(days=1))
    assert work.admin.delete(f"/holidays/{h.json()['id']}").status_code == 204
    assert run_reminder(owner_conn, "cron.daily_missing", work.today)


def test_a_holiday_is_an_admin_job_and_everyone_can_see_it(work):
    body = {"start_date": work.today.isoformat(), "end_date": work.today.isoformat()}
    assert work.m1.post("/holidays", body).status_code == 403
    h = work.admin.post("/holidays", body).json()
    assert [x["id"] for x in work.m1.get("/holidays").json()["items"]] == [h["id"]]
    assert work.m1.delete(f"/holidays/{h['id']}").status_code == 403
    assert work.admin.post("/holidays", {"start_date": "2026-12-25", "end_date": "2026-12-24"}).status_code == 422


# ------------------------------------------------------------------ leave
def test_people_on_leave_get_no_reminders(work, owner_conn):
    leave = work.m1.post("/leave", {"start_date": work.today.isoformat(), "end_date": (work.today + dt.timedelta(days=2)).isoformat(), "note": "Fever"})
    assert leave.status_code == 201
    morning = run_reminder(owner_conn, "cron.morning_plan", work.today)
    assert "mia.member@acme.com" not in morning and "max.member@acme.com" in morning  # Mia is away, Max is not
    assert "mia.member@acme.com" not in run_reminder(owner_conn, "cron.daily_missing", work.today)
    assert "mia.member@acme.com" not in run_reminder(owner_conn, "cron.due", work.today)  # Mia has a task due tomorrow and one overdue
    assert work.m1.delete(f"/leave/{leave.json()['id']}").status_code == 204
    assert "mia.member@acme.com" in run_reminder(owner_conn, "cron.daily_missing", work.today)


def test_leave_ended_yesterday_does_not_count(work, owner_conn):
    y = (work.today - dt.timedelta(days=1)).isoformat()
    work.m1.post("/leave", {"start_date": y, "end_date": y}).raise_for_status()
    assert "mia.member@acme.com" in run_reminder(owner_conn, "cron.daily_missing", work.today)


def test_leave_is_personal(work):
    mine = work.m1.post("/leave", {"start_date": "2026-12-01", "end_date": "2026-12-03"}).json()
    assert [x["id"] for x in work.m1.get("/leave").json()["items"]] == [mine["id"]]
    assert work.m2.get("/leave").json()["items"] == []  # nobody else sees it here
    assert work.m2.delete(f"/leave/{mine['id']}").status_code == 404  # nor deletes it
    assert work.admin.delete(f"/leave/{mine['id']}").status_code == 404
    holiday = work.admin.post("/holidays", {"start_date": "2026-12-25", "end_date": "2026-12-25"}).json()
    assert work.m1.delete(f"/leave/{holiday['id']}").status_code == 404  # a holiday id is not leave
    assert work.m1.get("/leave").json()["items"][0]["id"] == mine["id"]
    assert work.m1.post("/leave", {"start_date": "2026-12-05", "end_date": "2026-12-01"}).status_code == 422
    assert work.m1.post("/leave", {"start_date": "2026-01-01", "end_date": "2028-01-01"}).status_code == 422  # longer than a year


# ------------------------------------------------------------------ reminders per role, and the wording
def role_ids(api):
    return {r["name"]: r["id"] for r in api.get("/settings/reminders").json()["roles"]}


def put_reminder(api, kind, **body):
    return api.put(f"/settings/reminders/{kind}", body)


def test_reminder_settings_list_every_reminder_with_its_defaults(org):
    r = org.admin.get("/settings/reminders").json()
    assert [k["kind"] for k in r["kinds"]] == ["morning_plan", "daily_missing", "due", "team_overdue", "blocker"]
    morning = r["kinds"][0]
    assert morning["subject"] == morning["default_subject"] == "Share your plan for today" and "{name}" in morning["body"] and morning["time"] == "10:00"
    assert morning["roles_off"] == [] and r["kinds"][3]["time"] is None
    assert {"Team Member", "Team Lead", "Manager", "Company Admin"} <= set(role_ids(org.admin))
    assert org.m1.get("/settings/reminders").status_code == 403 and put_reminder(org.m1, "due").status_code == 403


def test_a_reminder_can_be_switched_off_for_a_role(work, owner_conn):
    put_reminder(work.admin, "morning_plan", roles_off=[role_ids(work.admin)["Team Member"]]).raise_for_status()
    morning = run_reminder(owner_conn, "cron.morning_plan", work.today)
    assert "mia.member@acme.com" not in morning and "max.member@acme.com" not in morning  # Team Members: off
    assert "leo.lead@acme.com" in morning and "maya.manager@acme.com" in morning  # other roles: still on
    assert "max.member@acme.com" in run_reminder(owner_conn, "cron.daily_missing", work.today)  # each reminder has its own switches
    put_reminder(work.admin, "morning_plan", roles_off=[]).raise_for_status()
    assert "max.member@acme.com" in run_reminder(owner_conn, "cron.morning_plan", work.today)


def test_team_overdue_and_blocker_follow_the_role_switches_too(work, owner_conn):
    lead = role_ids(work.admin)["Team Lead"]
    assert "leo.lead@acme.com" in run_reminder(owner_conn, "cron.due", work.today)  # Leo leads the team of the overdue task
    put_reminder(work.admin, "team_overdue", roles_off=[lead]).raise_for_status()
    mail.outbox.clear()
    run_reminder(owner_conn, "cron.due", work.today)
    assert "Overdue tasks in your team" not in [m["subject"] for m in mail.outbox if m["to"] == "leo.lead@acme.com"]
    put_reminder(work.admin, "blocker", roles_off=[lead]).raise_for_status()
    mail.outbox.clear()
    work.m2.patch(f"/tasks/{work.tasks['t2']['id']}", {"status": "blocked"}).raise_for_status()
    drain()
    assert not [m for m in mail.outbox if m["to"] == "leo.lead@acme.com" and m["subject"].startswith("Blocked")]


def test_the_wording_is_editable_with_placeholders(work, owner_conn):
    r = put_reminder(work.admin, "morning_plan", subject="Plan time, {name}", body="Hi {name}, tell us your plan for {date}: {link}")
    assert r.status_code == 200 and r.json()["subject"] == "Plan time, {name}"
    run_reminder(owner_conn, "cron.morning_plan", work.today)
    mia = next(m for m in mail.outbox if m["to"] == "mia.member@acme.com" and m["subject"].startswith("Plan time"))
    assert mia["subject"] == "Plan time, Mia Member" and f"plan for {work.today:%d %b}: http://web.test/my-day" in mia["text"]
    # an empty or default wording goes back to the built-in text
    put_reminder(work.admin, "morning_plan", subject="", body="").raise_for_status()
    got = work.admin.get("/settings/reminders").json()["kinds"][0]
    assert got["subject"] == "Share your plan for today" and got["body"] == got["default_body"]
    run_reminder(owner_conn, "cron.morning_plan", work.today)
    assert "Share your plan for today" in {m["subject"] for m in mail.outbox if m["to"] == "mia.member@acme.com"}


def test_reminder_wording_is_validated(org):
    a = org.admin
    assert put_reminder(a, "morning_plan", body="Hello {nam}").json()["code"] == "unknown_placeholder"
    assert put_reminder(a, "blocker", subject="Hi {name}").json()["code"] == "unknown_placeholder"  # {name} is not available for a blocker mail
    assert put_reminder(a, "morning_plan", roles_off=["00000000-0000-0000-0000-000000000000"]).json()["code"] == "invalid_role"
    assert put_reminder(a, "nope").status_code == 404
    assert put_reminder(a, "team_overdue", time="08:00").json()["code"] == "no_time"
    assert put_reminder(a, "morning_plan", subject="x" * 151).status_code == 422
    assert put_reminder(a, "morning_plan", body="Braces {} and {not a name} stay as text").status_code == 200


def test_a_reminder_time_is_set_with_its_reminder(org):
    assert put_reminder(org.admin, "daily_missing", time="16:30").json()["time"] == "16:30"
    assert org.admin.get("/settings").json()["reminder_eod_time"] == "16:30"
    assert put_reminder(org.admin, "morning_plan", time="17:00").json()["code"] == "invalid_reminder_times"
    assert put_reminder(org.admin, "due", time="06:45").json()["time"] == "06:45"
