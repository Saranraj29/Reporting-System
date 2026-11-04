"""Background worker: same codebase and image as the API, started with `python -m app.worker`.
Picks up jobs from PostgreSQL, fires the time-based schedules, sends mail/Slack, calls the AI model and
writes report files."""

import logging
import time
import traceback
from datetime import UTC, datetime
from datetime import time as dtime

from sqlalchemy import select, text

from .config import get_settings
from .db import new_session
from .models import ReportTemplate
from .services import jobs
from .services.handlers import HANDLERS, ON_FAILURE
from .services.timeutil import company_now

log = logging.getLogger("worker")


def schedule_tick(now: datetime | None = None) -> int:
    """Enqueue the cron-style jobs that are due. Dedupe keys make this safe to call every few seconds
    and let it catch up after downtime within the same local day."""
    now = now or datetime.now(UTC)
    queued = 0
    db = new_session()
    try:
        companies = db.execute(text("SELECT * FROM worker_companies()")).all()
        for c in companies:
            local = company_now(c.timezone, now)
            day, t, wk = local.date(), local.time(), local.weekday()
            cid = str(c.id)
            if wk < 5 and t >= dtime(10, 0):
                queued += jobs.enqueue(db, "cron.morning_plan", cid, {"date": day.isoformat()}, dedupe_key=f"morning:{cid}:{day}")
            if wk < 5 and t >= dtime(17, 30):
                queued += jobs.enqueue(db, "cron.daily_missing", cid, {"date": day.isoformat()}, dedupe_key=f"daily:{cid}:{day}")
            if t >= dtime(9, 0):
                queued += jobs.enqueue(db, "cron.due", cid, {"date": day.isoformat()}, dedupe_key=f"due:{cid}:{day}")
            if c.report_email_day is not None and t >= dtime(7, 0):
                if wk == c.report_email_day:
                    iso = local.isocalendar()
                    queued += jobs.enqueue(db, "cron.report_email", cid, {"kind": "weekly"}, dedupe_key=f"rep-w:{cid}:{iso.year}-{iso.week}")
                if day.day == 1:
                    queued += jobs.enqueue(db, "cron.report_email", cid, {"kind": "monthly"}, dedupe_key=f"rep-m:{cid}:{day:%Y-%m}")
            weekly_due = wk == 4 and t >= dtime(16, 0)  # Friday 16:00 company time
            monthly_due = day.day == 1 and t >= dtime(7, 0)
            if weekly_due or monthly_due:
                tdb = new_session(c.id)
                try:
                    for tpl in tdb.execute(select(ReportTemplate).where(ReportTemplate.schedule != "none")).scalars():
                        if (tpl.schedule == "weekly" and weekly_due) or (tpl.schedule == "monthly" and monthly_due):
                            queued += jobs.enqueue(db, "cron.template", cid, {"template_id": str(tpl.id)}, dedupe_key=f"tpl:{tpl.id}:{day}")
                finally:
                    tdb.close()
        db.commit()
    finally:
        db.close()
    return queued


def run_job(qdb, job) -> bool:
    """Execute one claimed job. Returns True on success."""
    s = get_settings()
    fn = HANDLERS.get(job.kind)
    tdb = new_session(job.company_id)
    try:
        if fn is None:
            raise RuntimeError(f"no handler for job kind {job.kind}")
        fn(tdb, job)
        tdb.commit()
        jobs.mark_done(qdb, job)
        return True
    except Exception as exc:  # noqa: BLE001
        tdb.rollback()
        err = f"{type(exc).__name__}: {exc}"
        log.warning("job %s (%s) attempt %s failed: %s", job.id, job.kind, job.attempts, err)
        log.debug(traceback.format_exc())
        will_retry = jobs.mark_failed_attempt(qdb, job, err, s.job_backoff_seconds)
        if not will_retry and job.kind in ON_FAILURE:
            fdb = new_session(job.company_id)
            try:
                ON_FAILURE[job.kind](fdb, job, err)
                fdb.commit()
            except Exception:  # noqa: BLE001
                fdb.rollback()
                log.exception("failure hook for %s failed", job.kind)
            finally:
                fdb.close()
        return False
    finally:
        tdb.close()


def run_pending(max_jobs: int = 1000) -> int:
    """Process due jobs until none are left (or max_jobs). Returns how many were attempted."""
    n = 0
    while n < max_jobs:
        qdb = new_session()
        try:
            job = jobs.claim_next(qdb)
            if job is None:
                return n
            run_job(qdb, job)
            n += 1
        finally:
            qdb.close()
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    log.info("worker started")
    last_tick = 0.0
    while True:
        try:
            if time.monotonic() - last_tick >= 60:
                schedule_tick()
                last_tick = time.monotonic()
            if run_pending() == 0:
                time.sleep(s.worker_poll_seconds)
        except Exception:  # noqa: BLE001
            log.exception("worker loop error")
            time.sleep(s.worker_poll_seconds)


if __name__ == "__main__":
    main()
