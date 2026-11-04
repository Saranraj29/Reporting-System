"""Background job handlers. Each runs in a tenant session for job.company_id."""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    Company,
    DailyStatus,
    Job,
    Project,
    ProjectMember,
    ReportRun,
    ReportShare,
    ReportTemplate,
    RolePermission,
    Task,
    TaskAssignee,
    Team,
    TeamMember,
    TimeEntry,
    User,
    UserRole,
)
from . import jobs, mail, runs, storage
from .access import load_permissions
from .notify import deliver
from .timeutil import company_today

log = logging.getLogger("handlers")
Handler = Callable[[Session, Job], None]
HANDLERS: dict[str, Handler] = {}
ON_FAILURE: dict[str, Callable[[Session, Job, str], None]] = {}


def handler(kind: str):
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return deco


def _company(db: Session, job: Job) -> Company:
    c = db.get(Company, job.company_id)
    if c is None:
        raise RuntimeError("company not found")
    return c


def _web(path: str) -> str:
    return f"{get_settings().public_web_url}{path}"


def users_with(db: Session, *keys: str) -> list[User]:
    """Active users holding at least one of the given permission keys (any role)."""
    ids = select(UserRole.user_id).join(RolePermission, RolePermission.role_id == UserRole.role_id).where(
        RolePermission.permission_key.in_(keys))
    return list(db.execute(select(User).where(User.id.in_(ids), User.is_active.is_(True),
                                              User.email_verified_at.is_not(None))).scalars())


def _enqueue_notify(db: Session, company_id, user: User, kind: str, subject: str, body: str) -> None:
    jobs.enqueue(db, "notify", company_id, {"kind": kind, "user_id": str(user.id), "subject": subject, "body": body})


# ------------------------------------------------------------------------------ notifications
@handler("notify")
def notify(db: Session, job: Job) -> None:
    user = db.get(User, uuid.UUID(job.payload["user_id"]))
    if user is None or not user.is_active:
        return
    p = job.payload
    deliver(db, job, _company(db, job), user, user.email, p["kind"], p["subject"], p["body"])


@handler("notify.blocker")
def notify_blocker(db: Session, job: Job) -> None:
    task = db.get(Task, uuid.UUID(job.payload["task_id"]))
    if task is None or not task.is_blocked:
        return
    actor = job.payload.get("actor_id")
    project = db.get(Project, task.project_id)
    assignee_ids = list(db.execute(select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id)).scalars())
    team_ids = select(TeamMember.team_id).where(TeamMember.user_id.in_(assignee_ids))
    leads = set(db.execute(select(Team.lead_user_id).where(Team.id.in_(team_ids))).scalars())
    member_ids = set(db.execute(select(ProjectMember.user_id).where(ProjectMember.project_id == task.project_id)).scalars())
    recipients: dict[uuid.UUID, User] = {}
    for u in users_with(db, "task.view.team", "task.view.all"):
        if u.id in leads or u.id in member_ids or u.id in {*assignee_ids}:
            recipients[u.id] = u
    for u in db.execute(select(User).where(User.id.in_([x for x in leads if x]))).scalars():
        recipients[u.id] = u
    recipients.pop(uuid.UUID(actor), None) if actor else None
    subject = f"Blocked: {task.title}"
    body = f"The task “{task.title}” in {project.name if project else 'a project'} was marked as blocked.\n{_web('/tasks')}"
    for u in recipients.values():
        _enqueue_notify(db, job.company_id, u, "blocker", subject, body)


@handler("cron.daily_missing")
def cron_daily_missing(db: Session, job: Job) -> None:
    day = date.fromisoformat(job.payload["date"])
    has_status = select(DailyStatus.user_id).where(DailyStatus.status_date == day)
    has_time = select(TimeEntry.user_id).where(TimeEntry.entry_date == day)
    users = db.execute(
        select(User).where(User.is_active.is_(True), User.email_verified_at.is_not(None),
                           User.id.not_in(has_status), User.id.not_in(has_time))
    ).scalars()
    for u in users:
        _enqueue_notify(db, job.company_id, u, "daily_missing", "Please log today's status and time",
                        f"Hi {u.name}, nothing is logged for {day:%d %b}. Add your daily status and hours:\n{_web('/my-day')}")


@handler("cron.due")
def cron_due(db: Session, job: Job) -> None:
    today = date.fromisoformat(job.payload["date"])
    soon = today + timedelta(days=1)
    rows = db.execute(
        select(Task, TaskAssignee.user_id).join(TaskAssignee, TaskAssignee.task_id == Task.id)
        .where(Task.status != "done", Task.due_date.is_not(None), Task.due_date <= soon)
    ).all()
    per_user: dict[uuid.UUID, dict[str, list[str]]] = {}
    for task, uid in rows:
        bucket = per_user.setdefault(uid, {"due": [], "overdue": []})
        bucket["overdue" if task.due_date < today else "due"].append(task.title)
    # team leads hear about their team's overdue work
    lead_overdue: dict[uuid.UUID, list[str]] = {}
    for uid, b in per_user.items():
        if not b["overdue"]:
            continue
        team_ids = select(TeamMember.team_id).where(TeamMember.user_id == uid)
        for lead in db.execute(select(Team.lead_user_id).where(Team.id.in_(team_ids))).scalars():
            if lead and lead != uid:
                lead_overdue.setdefault(lead, []).extend(b["overdue"])
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_({*per_user, *lead_overdue}))).scalars()}
    for uid, b in per_user.items():
        lines = [f"- due soon: {t}" for t in b["due"]] + [f"- overdue: {t}" for t in b["overdue"]]
        if uid in users:
            _enqueue_notify(db, job.company_id, users[uid], "due", "Tasks due soon or overdue", "\n".join(lines) + f"\n{_web('/tasks')}")
    for lead, titles in lead_overdue.items():
        if lead in users:
            _enqueue_notify(db, job.company_id, users[lead], "team_overdue", "Overdue tasks in your team",
                            "\n".join(f"- {t}" for t in titles) + f"\n{_web('/tasks')}")


# ------------------------------------------------------------------------------ reports
def _run(db: Session, job: Job) -> ReportRun:
    run = db.get(ReportRun, uuid.UUID(job.payload["run_id"]))
    if run is None:
        raise RuntimeError("report run not found")
    return run


def _notify_requester(db: Session, run: ReportRun, kind: str, subject: str, body: str) -> None:
    if run.requested_by:
        u = db.get(User, run.requested_by)
        if u and u.is_active:
            _enqueue_notify(db, run.company_id, u, kind, subject, body)


@handler("report.generate")
def report_generate(db: Session, job: Job) -> None:
    run = _run(db, job)
    company = _company(db, job)
    run.figures = runs.compute_figures(db, run, company)
    runs.build_files(db, run, company, [run.export_format or "pdf"])
    run.status, run.error = "ready", None
    db.commit()
    _notify_requester(db, run, "report_ready", f"Report ready: {runs.run_title(run)}",
                      f"Your {run.export_format or 'pdf'} export is ready:\n{_web(f'/reports/runs/{run.id}')}")


@handler("report.draft")
def report_draft(db: Session, job: Job) -> None:
    from .ai import draft_report_text

    run = _run(db, job)
    company = _company(db, job)
    tpl = run.params["template"]
    if not run.figures or job.payload.get("recompute", True):
        run.figures = runs.compute_figures(db, run, company)
    ai_text, provider = draft_report_text(
        run.figures, tpl, note=run.redraft_note, previous=run.ai_text, figures_only=bool(job.payload.get("figures_only")),
    )
    run.ai_text, run.ai_provider, run.error, run.status = ai_text, provider, None, "drafted"
    db.commit()
    if tpl["audience"] == "internal":  # internal reports skip approval and sharing
        jobs.enqueue(db, "report.finalize", job.company_id, {"run_id": str(run.id), "mark_ready": True})
        return
    subject = f"Draft ready for review: {runs.run_title(run)}"
    body = f"A client report draft is waiting for review:\n{_web(f'/client-reports/runs/{run.id}')}"
    recipients = {u.id: u for u in users_with(db, "report.approve")}
    if run.requested_by and (u := db.get(User, run.requested_by)):
        recipients[u.id] = u
    for u in recipients.values():
        _enqueue_notify(db, job.company_id, u, "report_drafted", subject, body)


@handler("report.finalize")
def report_finalize(db: Session, job: Job) -> None:
    run = _run(db, job)
    runs.build_files(db, run, _company(db, job), ["pdf", "docx", "xlsx"])
    if job.payload.get("mark_ready"):
        run.status = "ready"
    db.commit()


@handler("report.share")
def report_share(db: Session, job: Job) -> None:
    run = _run(db, job)
    company = _company(db, job)
    if not run.file_url_pdf:
        raise RuntimeError("final files are not rendered yet")
    pdf = storage.get(run.file_url_pdf)
    shares = db.execute(select(ReportShare).where(ReportShare.report_run_id == run.id, ReportShare.emailed_at.is_(None),
                                                  ReportShare.revoked_at.is_(None))).scalars().all()
    errors = []
    for s in shares:
        try:
            link = _web(f"/shared/{s.token}")
            mail.send_email(s.recipient_email, f"{runs.run_title(run)} — {company.name}",
                            f"{company.name} shared a report with you.\nView it online (expires {s.expires_at:%d %b %Y}):\n{link}\n",
                            attachments=[("report.pdf", pdf, "application/pdf")])
            s.emailed_at = datetime.now(UTC)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            errors.append(f"{s.recipient_email}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))
    run.status = "sent"
    db.commit()


def _fail_run(db: Session, job: Job, error: str) -> None:
    run = db.get(ReportRun, uuid.UUID(job.payload["run_id"])) if job.payload.get("run_id") else None
    if run is None:
        return
    # a failed share/finalize must not wipe an approved run's draft
    if job.kind in ("report.generate", "report.draft"):
        run.status = "failed"
    run.error = error[:500]
    db.commit()
    _notify_requester(db, run, "report_failed", f"Report failed: {runs.run_title(run)}", f"The job {job.kind} failed: {error[:200]}")


for _k in ("report.generate", "report.draft", "report.finalize", "report.share"):
    ON_FAILURE[_k] = _fail_run


# ------------------------------------------------------------------------------ scheduled reports
def _create_run(db: Session, company: Company, report_key: str, start: date, end: date, *, requested_by,
                scope, params: dict, fmt: str | None = None, status: str = "queued", template_id=None) -> ReportRun:
    run = ReportRun(company_id=company.id, report_key=report_key, period_start=start, period_end=end,
                    requested_by=requested_by, scope_user_ids=scope, params=params, export_format=fmt, status=status,
                    template_id=template_id)
    db.add(run)
    db.flush()
    return run


@handler("cron.report_email")
def cron_report_email(db: Session, job: Job) -> None:
    from ..reports import REGISTRY
    from .access import visible_users

    company = _company(db, job)
    kind = job.payload["kind"]  # weekly | monthly
    defn = REGISTRY[kind]
    start, end = runs.previous_full_period(kind, company_today(company.timezone))
    for user in users_with(db, f"{defn.required_permission}.team", f"{defn.required_permission}.all"):
        perms = load_permissions(db, user.id, use_cache=False)
        _, ids = visible_users(db, user.id, perms, defn.required_permission)
        run = _create_run(db, company, kind, start, end, requested_by=user.id, params={}, fmt="pdf",
                          scope=None if ids is None else sorted(str(i) for i in ids))
        jobs.enqueue(db, "report.generate", company.id, {"run_id": str(run.id)})


@handler("cron.template")
def cron_template(db: Session, job: Job) -> None:
    company = _company(db, job)
    tpl = db.get(ReportTemplate, uuid.UUID(job.payload["template_id"]))
    if tpl is None or tpl.schedule == "none":
        return
    start, end = runs.previous_full_period(tpl.base_report, company_today(company.timezone))
    run = _create_run(db, company, tpl.base_report, start, end, requested_by=None, scope=None,
                      params={"template": runs.template_snapshot(tpl)}, template_id=tpl.id)
    jobs.enqueue(db, "report.draft", company.id, {"run_id": str(run.id)})


