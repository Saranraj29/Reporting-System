"""Job queue inside PostgreSQL (SELECT ... FOR UPDATE SKIP LOCKED): jobs are written in the same
transaction as the data change that caused them, so they are never lost."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import Job


def enqueue(
    db: Session,
    kind: str,
    company_id: uuid.UUID | str | None = None,
    payload: dict[str, Any] | None = None,
    run_at: datetime | None = None,
    dedupe_key: str | None = None,
    queue: str | None = None,
) -> bool:
    """Adds a job to the caller's transaction. Returns False if dedupe_key already exists.
    AI jobs (kind 'ai_*') go to the 'ai' lane so a slow model call never delays reminders, Slack or scheduled exports."""
    values: dict[str, Any] = {
        "kind": kind,
        "company_id": uuid.UUID(str(company_id)) if company_id else None,
        "payload": payload or {},
        "dedupe_key": dedupe_key,
        "queue": queue or ("ai" if kind.startswith("ai_") else "default"),
    }
    if run_at:
        values["run_at"] = run_at
    stmt = pg_insert(Job).values(**values).on_conflict_do_nothing(index_elements=["dedupe_key"]).returning(Job.id)
    return db.execute(stmt).first() is not None


def claim_next(db: Session, queue: str | None = None) -> Job | None:
    """queue None = any lane (tests, single-worker setups); otherwise only that lane."""
    # jobs stuck in 'running' (worker crashed) become runnable again after 10 minutes
    db.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at < func.now() - timedelta(minutes=10))
        .values(status="queued")
    )
    stmt = select(Job).where(Job.status == "queued", Job.run_at <= func.now())
    if queue is not None:
        stmt = stmt.where(Job.queue == queue)
    job = db.execute(
        stmt
        .order_by(Job.run_at, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is not None:
        job.status = "running"
        job.locked_at = datetime.now(UTC)
        job.attempts += 1
    db.commit()
    return job


def mark_done(db: Session, job: Job) -> None:
    job.status, job.finished_at, job.last_error = "done", datetime.now(UTC), None
    db.commit()


def mark_failed_attempt(db: Session, job: Job, error: str, backoff_seconds: int) -> bool:
    """Returns True if the job will be retried, False if it is out of attempts."""
    job.last_error = error[:2000]
    if job.attempts >= job.max_attempts:
        job.status, job.finished_at = "failed", datetime.now(UTC)
        db.commit()
        return False
    job.status = "queued"
    job.run_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds * (2 ** (job.attempts - 1)))
    db.commit()
    return True
