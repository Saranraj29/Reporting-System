import datetime as dt

from app.services import mail
from app.worker import schedule_tick

from .conftest import add_user, drain, role_id


def subjects(to=None):
    return [m["subject"] for m in mail.outbox if to is None or m["to"] == to]


def test_blocker_notifies_lead_and_project_managers_but_not_the_actor(work):
    mail.outbox.clear()
    t = work.tasks["t2"]  # Max's task
    work.m2.patch(f"/tasks/{t['id']}", {"status": "blocked"}).raise_for_status()
    drain()
    assert "Blocked: Build API" in subjects("leo.lead@acme.com")  # lead of Max's team
    assert "Blocked: Build API" not in subjects("max.member@acme.com")  # actor
    assert "Blocked: Build API" not in subjects("olive.outsider@acme.com")


def test_daily_status_reminder_goes_only_to_people_with_nothing_logged(work, owner_conn):
    from app.db import session_scope
    from app.services import jobs

    work.m1.put(f"/daily-status/{work.today}", {"did_today": "x"}).raise_for_status()
    cid = owner_conn.execute("SELECT id FROM companies").fetchone()[0]
    with session_scope(cid) as db:
        jobs.enqueue(db, "cron.daily_missing", cid, {"date": work.today.isoformat()})
    mail.outbox.clear()
    drain()
    reminded = {m["to"] for m in mail.outbox if "end-of-day update" in m["subject"]}
    # only Mia posted an end-of-day update; logging hours alone does not count
    assert reminded == {"admin@acme.com", "maya.manager@acme.com", "leo.lead@acme.com", "max.member@acme.com", "olive.outsider@acme.com"}


def test_schedule_tick_times_dedupe_and_timezones(org, owner_conn):
    org.admin.patch("/settings", {"timezone": "Asia/Kolkata"}).raise_for_status()
    kinds = lambda: sorted(r[0] for r in owner_conn.execute("SELECT kind FROM jobs WHERE kind LIKE 'cron.%' AND kind <> 'cron.ai_retention'"))  # the nightly AI-record purge has its own test  # noqa: E731
    monday_11_30_utc = dt.datetime(2026, 11, 2, 11, 30, tzinfo=dt.UTC)  # 17:00 in Kolkata
    schedule_tick(monday_11_30_utc)
    assert kinds() == ["cron.due", "cron.morning_plan", "cron.report_email"]  # >= 09:00 / 10:00 / 07:00 (report day Monday); not yet 17:30
    schedule_tick(monday_11_30_utc + dt.timedelta(minutes=45))  # 18:15 local
    assert kinds() == ["cron.daily_missing", "cron.due", "cron.morning_plan", "cron.report_email"]
    schedule_tick(monday_11_30_utc + dt.timedelta(minutes=50))  # same day again: nothing new
    assert len(kinds()) == 4
    sat = dt.datetime(2026, 11, 7, 14, 0, tzinfo=dt.UTC)
    owner_conn.execute("TRUNCATE jobs")
    schedule_tick(sat)
    assert kinds() == ["cron.due"]  # no weekday reminder, no Monday report on a Saturday
    owner_conn.execute("TRUNCATE jobs")
    schedule_tick(dt.datetime(2026, 12, 1, 3, 0, tzinfo=dt.UTC))  # 08:30 Kolkata on the 1st: monthly report not before 07:00? it is after
    assert "cron.report_email" in kinds()


def test_due_soon_and_overdue_digests(work, owner_conn):
    from app.db import session_scope
    from app.services import jobs

    cid = owner_conn.execute("SELECT id FROM companies").fetchone()[0]
    with session_scope(cid) as db:
        jobs.enqueue(db, "cron.due", cid, {"date": work.today.isoformat()})
    mail.outbox.clear()
    drain()
    mia = [m for m in mail.outbox if m["to"] == "mia.member@acme.com" and m["subject"] == "Tasks due soon or overdue"]
    # "Ship login" is done so it is not reported; "Write docs" is 3 days overdue
    assert mia and "overdue: Write docs" in mia[0]["text"] and "Ship login" not in mia[0]["text"]
    lead = [m for m in mail.outbox if m["to"] == "leo.lead@acme.com" and "Overdue" in m["subject"]]
    assert lead and "Write docs" in lead[0]["text"]  # leads hear about their team's overdue work
    assert not [m for m in mail.outbox if m["to"] == "olive.outsider@acme.com" and "Overdue tasks in your team" in m["subject"]]


def test_scheduled_weekly_report_email(work, owner_conn):
    work.admin.patch("/settings", {"report_email_enabled": True, "report_email_day": 0}).raise_for_status()
    monday = dt.datetime(2026, 11, 2, 7, 5, tzinfo=dt.UTC)
    mail.outbox.clear()
    schedule_tick(monday)
    drain()
    ready = [m for m in mail.outbox if m["subject"].startswith("Report ready")]
    recipients = {m["to"] for m in ready}
    assert {"leo.lead@acme.com", "maya.manager@acme.com", "admin@acme.com"} <= recipients  # holders of a weekly report key
    assert "mia.member@acme.com" not in recipients
    work.admin.patch("/settings", {"report_email_enabled": False}).raise_for_status()
    owner_conn.execute("TRUNCATE jobs")
    schedule_tick(dt.datetime(2026, 11, 9, 7, 5, tzinfo=dt.UTC))
    assert owner_conn.execute("SELECT count(*) FROM jobs WHERE kind = 'cron.report_email'").fetchone()[0] == 0


def _job_for(owner_conn, kind="notify"):
    return owner_conn.execute("SELECT status, attempts, last_error FROM jobs WHERE kind = %s ORDER BY id", (kind,)).fetchall()


def test_failed_sends_retry_three_times_then_stay_failed_in_the_log(work, monkeypatch, owner_conn):
    calls = []

    def boom(to, *a, **k):
        calls.append(to)
        raise ConnectionError("smtp down")

    monkeypatch.setattr(mail, "send_email", boom)
    work.m2.patch(f"/tasks/{work.tasks['t2']['id']}", {"status": "blocked"}).raise_for_status()
    drain()
    status = _job_for(owner_conn)
    assert status and all((r[0], r[1]) == ("failed", 3) for r in status)
    assert len(calls) == 3 * len(status)
    log = work.admin.get("/notifications", params={"status": "failed"}).json()
    assert log["total"] == len(status) and log["items"][0]["channel"] == "email" and "smtp down" in log["items"][0]["error"]


def test_slack_gets_the_same_text_and_only_failed_channels_are_retried(work, monkeypatch):
    drain()  # flush notifications queued while seeding
    work.admin.patch("/settings", {"slack_webhook_url": "https://hooks.slack.com/services/T/B/XYZ"}).raise_for_status()
    slack, emails = [], []
    attempts = {"n": 0}

    def flaky_slack(url, text):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionError("slack 500")
        slack.append((url, text))

    monkeypatch.setattr(mail, "post_slack", flaky_slack)
    real_send = mail.send_email
    monkeypatch.setattr(mail, "send_email", lambda to, *a, **k: (emails.append(to), real_send(to, *a, **k))[1])
    work.m2.patch(f"/tasks/{work.tasks['t2']['id']}", {"status": "blocked"}).raise_for_status()
    drain()
    assert slack and slack[0][0] == "https://hooks.slack.com/services/T/B/XYZ"  # decrypted webhook used
    assert "Build API" in slack[0][1]
    assert len(emails) == len(set(emails))  # the email channel succeeded first time and was not re-sent on retry
    log = work.admin.get("/notifications").json()["items"]
    assert {i["channel"] for i in log} == {"email", "slack"} and all(i["status"] == "sent" for i in log)
    assert emails == ["leo.lead@acme.com"]


def test_job_handlers_run_in_the_right_tenant(org, client, owner_conn):
    """Two companies, a blocker in A must not create notifications in B."""
    from .conftest import signup_admin

    b = signup_admin(client, "globex.com", "Globex")
    add_user(b, "Zed Lead", "Team Lead", domain="globex.com")
    p = org.admin.post("/projects", {"name": "P"}).json()
    org.admin.put(f"/projects/{p['id']}/members", {"user_ids": [org.m1.user_id]})  # members add tasks only to their own projects
    t = org.m1.post("/tasks", {"project_id": p["id"], "title": "Blocked thing"}).json()
    mail.outbox.clear()
    org.m1.patch(f"/tasks/{t['id']}", {"status": "blocked"}).raise_for_status()
    drain()
    assert all(m["to"].endswith("@acme.com") for m in mail.outbox)
    assert b.get("/notifications").json()["total"] == 0 and role_id(b, "Manager")


def test_queue_claims_each_job_once(org, owner_conn):
    from app.db import new_session
    from app.services import jobs

    drain()  # sign-up queues e-mails (verification): start from an empty queue
    cid = owner_conn.execute("SELECT id FROM companies").fetchone()[0]
    s = new_session()
    jobs.enqueue(s, "noop", cid, {}, dedupe_key="k1")
    assert jobs.enqueue(s, "noop", cid, {}, dedupe_key="k1") is False  # deduped
    s.commit()
    a, b = new_session(), new_session()
    ja = jobs.claim_next(a)
    jb = jobs.claim_next(b)
    assert ja is not None and jb is None  # second worker finds nothing: already running
    assert ja.attempts == 1 and ja.status == "running"
    for x in (s, a, b):
        x.close()
