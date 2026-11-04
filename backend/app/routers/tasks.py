"""Tasks, comments, time entries (manual + timer) and daily status."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from ..deps import Ctx, Page, paged, pagination, require, require_any
from ..errors import ApiError, bad_request, conflict, forbidden, not_found
from ..models import (
    DailyStatus,
    Project,
    Task,
    TaskAssignee,
    TaskComment,
    TaskFieldDefinition,
    TimeEntry,
    User,
)
from ..services import jobs
from ..services.access import owned_project_ids
from ..services.timeutil import company_today, tzinfo

router = APIRouter(tags=["tasks"])

STATUSES = ("todo", "in_progress", "blocked", "in_review", "done")
PRIORITIES = ("low", "medium", "high", "urgent")


# --------------------------------------------------------------------------- helpers
def _scope_clause(ids: set[uuid.UUID] | None, owned: list[uuid.UUID] | None = None):
    """Tasks I may see: assigned to someone in my scope, or inside a project I own."""
    if ids is None:
        return None
    clause = Task.id.in_(select(TaskAssignee.task_id).where(TaskAssignee.user_id.in_(ids)))
    return clause | Task.project_id.in_(owned) if owned else clause


def _visible_task(ctx: Ctx, task_id: uuid.UUID) -> Task:
    ids = ctx.visible("task.view")
    stmt = select(Task).where(Task.id == task_id)
    clause = _scope_clause(ids, owned_project_ids(ctx.db, ctx.me.id))
    if clause is not None:
        stmt = stmt.where(clause)
    task = ctx.db.execute(stmt).scalar_one_or_none()
    if not task:
        raise not_found("Task")
    return task


def _can_edit(ctx: Ctx, task: Task) -> bool:
    if not ctx.scope_of("task.edit"):
        return False
    ids = ctx.visible("task.edit")
    if ids is None:
        return True
    return ctx.db.execute(
        select(func.count()).select_from(TaskAssignee).where(TaskAssignee.task_id == task.id, TaskAssignee.user_id.in_(ids))
    ).scalar_one() > 0


def _editable_task(ctx: Ctx, task_id: uuid.UUID) -> Task:
    task = _visible_task(ctx, task_id)
    if not _can_edit(ctx, task):
        raise forbidden("You cannot edit this task")
    return task


def _assignee_map(ctx: Ctx, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    out: dict[uuid.UUID, list[dict]] = {}
    rows = ctx.db.execute(
        select(TaskAssignee.task_id, User.id, User.name).join(User, User.id == TaskAssignee.user_id)
        .where(TaskAssignee.task_id.in_(task_ids)).order_by(User.name)
    )
    for tid, uid, name in rows:
        out.setdefault(tid, []).append({"id": str(uid), "name": name})
    return out


def _task_out(ctx: Ctx, tasks: list[Task]) -> list[dict]:
    ids = [t.id for t in tasks]
    if not ids:
        return []
    assignees = _assignee_map(ctx, ids)
    hours = dict(
        ctx.db.execute(select(TimeEntry.task_id, func.sum(TimeEntry.hours)).where(TimeEntry.task_id.in_(ids)).group_by(TimeEntry.task_id)).all()
    )
    projects = dict(ctx.db.execute(select(Project.id, Project.name).where(Project.id.in_({t.project_id for t in tasks}))).all())
    today = company_today(ctx.company.timezone)
    return [
        {
            "id": str(t.id), "project_id": str(t.project_id), "project_name": projects.get(t.project_id),
            "title": t.title, "description": t.description, "activity_type": t.activity_type,
            "priority": t.priority, "status": t.status,
            "eta_hours": float(t.eta_hours) if t.eta_hours is not None else None,
            "actual_hours": float(hours.get(t.id, Decimal(0))),  # derived from time_entries, never stored
            "start_date": t.start_date.isoformat() if t.start_date else None,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "is_blocked": t.is_blocked, "custom_fields": t.custom_fields,
            "overdue": bool(t.due_date and t.due_date < today and t.status != "done"),
            "assignees": assignees.get(t.id, []), "created_by": str(t.created_by) if t.created_by else None,
            "created_at": t.created_at.isoformat(), "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
        for t in tasks
    ]


def validate_custom_fields(defs: list[TaskFieldDefinition], values: dict[str, Any]) -> dict[str, Any]:
    active = {d.key: d for d in defs if d.is_active and not d.is_builtin}
    errors: dict[str, str] = {}
    clean: dict[str, Any] = {}
    for key in values:
        if key not in active:
            errors[key] = "unknown field"
    for key, d in active.items():
        v = values.get(key)
        if v in (None, ""):
            if d.required:
                errors[key] = "required"
            continue
        if d.type == "text" and isinstance(v, str):
            clean[key] = v
        elif d.type == "number" and isinstance(v, (int, float)) and not isinstance(v, bool):
            clean[key] = v
        elif d.type == "date" and isinstance(v, str):
            try:
                date.fromisoformat(v)
                clean[key] = v
            except ValueError:
                errors[key] = "must be an ISO date (YYYY-MM-DD)"
        elif d.type == "select" and isinstance(v, str) and v in d.options:
            clean[key] = v
        else:
            errors[key] = f"invalid value for a {d.type} field"
    if errors:
        raise bad_request("invalid_custom_fields", "Custom field validation failed", errors)
    return clean


def _field_defs(ctx: Ctx) -> list[TaskFieldDefinition]:
    return list(ctx.db.execute(select(TaskFieldDefinition)).scalars())


def _check_activity(defs: list[TaskFieldDefinition], value: str) -> None:
    d = next((d for d in defs if d.key == "activity_type" and d.is_builtin), None)
    if d and d.options and value not in d.options:
        raise bad_request("invalid_activity_type", f"activity_type must be one of: {', '.join(d.options)}")


def _check_assignees(ctx: Ctx, ids: list[uuid.UUID]) -> None:
    unique = set(ids)
    if not unique:
        raise bad_request("assignee_required", "A task needs at least one assignee")
    active = set(ctx.db.execute(select(User.id).where(User.id.in_(unique), User.is_active.is_(True))).scalars())
    if active != unique:
        raise bad_request("invalid_assignee", "One or more assignees do not exist or are inactive")
    allowed = ctx.visible("task.edit")
    if allowed is not None and not unique <= allowed:
        raise forbidden("You can only assign tasks to people within your scope")


# --------------------------------------------------------------------------- tasks
@router.get("/tasks")
def list_tasks(
    project: uuid.UUID | None = None, assignee: uuid.UUID | None = None, status: str | None = None,
    priority: str | None = None, due_from: date | None = None, due_to: date | None = None,
    q: str | None = None, overdue: bool | None = None, blocked: bool | None = None,
    ctx: Ctx = Depends(require("task.view")), page: Page = Depends(pagination),
):
    stmt = select(Task).order_by(Task.due_date.asc().nulls_last(), Task.created_at.desc())
    clause = _scope_clause(ctx.visible("task.view"), owned_project_ids(ctx.db, ctx.me.id))
    if clause is not None:
        stmt = stmt.where(clause)
    if project:
        stmt = stmt.where(Task.project_id == project)
    if assignee:
        stmt = stmt.where(Task.id.in_(select(TaskAssignee.task_id).where(TaskAssignee.user_id == assignee)))
    if status:
        stmt = stmt.where(Task.status == status)
    if priority:
        stmt = stmt.where(Task.priority == priority)
    if due_from:
        stmt = stmt.where(Task.due_date >= due_from)
    if due_to:
        stmt = stmt.where(Task.due_date <= due_to)
    if q:
        stmt = stmt.where(Task.title.ilike(f"%{q}%"))
    if blocked is not None:
        stmt = stmt.where(Task.is_blocked == blocked)
    if overdue:
        stmt = stmt.where(Task.due_date < company_today(ctx.company.timezone), Task.status != "done")
    result = paged(ctx.db, stmt, page, lambda t: t)
    result["items"] = _task_out(ctx, result["items"])
    return result


class TaskIn(BaseModel):
    project_id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    activity_type: str = "Development"
    priority: str = Field(default="medium", pattern="^(low|medium|high|urgent)$")
    status: str = Field(default="todo", pattern="^(todo|in_progress|blocked|in_review|done)$")
    eta_hours: float | None = Field(default=None, ge=0, le=9999)
    start_date: date | None = None
    due_date: date | None = None
    assignee_ids: list[uuid.UUID] = []
    custom_fields: dict[str, Any] = {}


class TaskPatch(BaseModel):
    project_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    activity_type: str | None = None
    priority: str | None = Field(default=None, pattern="^(low|medium|high|urgent)$")
    status: str | None = Field(default=None, pattern="^(todo|in_progress|blocked|in_review|done)$")
    eta_hours: float | None = Field(default=None, ge=0, le=9999)
    start_date: date | None = None
    due_date: date | None = None
    custom_fields: dict[str, Any] | None = None


def _apply_status(ctx: Ctx, task: Task, new_status: str) -> None:
    was_blocked = task.is_blocked
    task.status = new_status
    task.is_blocked = new_status == "blocked"
    if new_status == "done" and task.completed_at is None:
        task.completed_at = datetime.now(UTC)
    elif new_status != "done":
        task.completed_at = None
    if task.is_blocked and not was_blocked:
        jobs.enqueue(ctx.db, "notify.blocker", ctx.company_id, {"task_id": str(task.id), "actor_id": str(ctx.me.id)})


def _check_dates(start: date | None, due: date | None) -> None:
    if start and due and due < start:
        raise bad_request("invalid_dates", "Due date cannot be before the start date")


@router.post("/tasks", status_code=201)
def create_task(body: TaskIn, ctx: Ctx = Depends(require("task.edit"))):
    project = ctx.db.get(Project, body.project_id)
    if not project:
        raise bad_request("invalid_project", "Project does not exist")
    if project.status == "archived":
        raise bad_request("project_archived", "Cannot add tasks to an archived project")
    defs = _field_defs(ctx)
    _check_activity(defs, body.activity_type)
    _check_dates(body.start_date, body.due_date)
    custom = validate_custom_fields(defs, body.custom_fields)
    assignees = body.assignee_ids or [ctx.me.id]
    _check_assignees(ctx, assignees)
    task = Task(
        company_id=ctx.company_id, project_id=body.project_id, created_by=ctx.me.id, title=body.title.strip(),
        description=body.description, activity_type=body.activity_type, priority=body.priority,
        eta_hours=body.eta_hours, start_date=body.start_date, due_date=body.due_date, custom_fields=custom,
    )
    ctx.db.add(task)
    ctx.db.flush()
    ctx.db.add_all(TaskAssignee(company_id=ctx.company_id, task_id=task.id, user_id=u) for u in set(assignees))
    _apply_status(ctx, task, body.status)
    ctx.db.commit()
    return _task_out(ctx, [task])[0]


@router.get("/tasks/{task_id}")
def get_task(task_id: uuid.UUID, ctx: Ctx = Depends(require("task.view"))):
    task = _visible_task(ctx, task_id)
    out = _task_out(ctx, [task])[0]
    out["can_edit"] = _can_edit(ctx, task)
    return out


@router.patch("/tasks/{task_id}")
def patch_task(task_id: uuid.UUID, body: TaskPatch, ctx: Ctx = Depends(require("task.edit"))):
    task = _editable_task(ctx, task_id)
    data = body.model_dump(exclude_unset=True)
    defs = _field_defs(ctx)
    if data.get("activity_type"):
        _check_activity(defs, data["activity_type"])
    if "project_id" in data and data["project_id"]:
        if not ctx.db.get(Project, data["project_id"]):
            raise bad_request("invalid_project", "Project does not exist")
        task.project_id = data["project_id"]
    for k in ("title", "description", "activity_type", "priority", "eta_hours", "start_date", "due_date"):
        if k in data and not (data[k] is None and k in ("title", "activity_type", "priority", "description")):
            setattr(task, k, data[k].strip() if k == "title" else data[k])
    _check_dates(task.start_date, task.due_date)
    if data.get("custom_fields") is not None:
        task.custom_fields = validate_custom_fields(defs, {**task.custom_fields, **data["custom_fields"]})
    if data.get("status") and data["status"] != task.status:
        _apply_status(ctx, task, data["status"])
    ctx.db.commit()
    return _task_out(ctx, [task])[0]


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: uuid.UUID, ctx: Ctx = Depends(require("task.edit"))):
    task = _editable_task(ctx, task_id)
    ctx.db.delete(task)
    ctx.db.commit()


class AssigneesIn(BaseModel):
    user_ids: list[uuid.UUID]


@router.put("/tasks/{task_id}/assignees")
def set_assignees(task_id: uuid.UUID, body: AssigneesIn, ctx: Ctx = Depends(require("task.edit"))):
    task = _editable_task(ctx, task_id)
    _check_assignees(ctx, body.user_ids)
    ctx.db.execute(delete(TaskAssignee).where(TaskAssignee.task_id == task.id))
    ctx.db.add_all(TaskAssignee(company_id=ctx.company_id, task_id=task.id, user_id=u) for u in set(body.user_ids))
    ctx.db.commit()
    return _task_out(ctx, [task])[0]


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


@router.get("/tasks/{task_id}/comments")
def list_comments(task_id: uuid.UUID, ctx: Ctx = Depends(require("task.view"))):
    _visible_task(ctx, task_id)
    rows = ctx.db.execute(
        select(TaskComment, User.name).join(User, User.id == TaskComment.user_id)
        .where(TaskComment.task_id == task_id).order_by(TaskComment.created_at)
    ).all()
    return {"items": [
        {"id": str(c.id), "user_id": str(c.user_id), "user_name": n, "body": c.body, "created_at": c.created_at.isoformat()}
        for c, n in rows
    ]}


@router.post("/tasks/{task_id}/comments", status_code=201)
def add_comment(task_id: uuid.UUID, body: CommentIn, ctx: Ctx = Depends(require("task.view"))):
    _visible_task(ctx, task_id)
    c = TaskComment(company_id=ctx.company_id, task_id=task_id, user_id=ctx.me.id, body=body.body.strip())
    ctx.db.add(c)
    ctx.db.commit()
    return {"id": str(c.id), "user_id": str(c.user_id), "user_name": ctx.me.name, "body": c.body, "created_at": c.created_at.isoformat()}


# --------------------------------------------------------------------------- time entries
def _entry_out(e: TimeEntry, title: str | None = None, user_name: str | None = None) -> dict:
    return {
        "id": str(e.id), "task_id": str(e.task_id), "task_title": title, "user_id": str(e.user_id), "user_name": user_name,
        "hours": float(e.hours), "entry_date": e.entry_date.isoformat(), "note": e.note,
        "started_at": e.started_at.isoformat() if e.started_at else None,
        "running": bool(e.started_at and not e.stopped_at),
    }


def _loggable_task(ctx: Ctx, task_id: uuid.UUID) -> Task:
    """I may log time on tasks I am assigned to (or, with team/all edit scope, tasks I can edit)."""
    task = ctx.db.get(Task, task_id)
    if not task:
        raise not_found("Task")
    assigned = ctx.db.execute(
        select(func.count()).select_from(TaskAssignee).where(TaskAssignee.task_id == task_id, TaskAssignee.user_id == ctx.me.id)
    ).scalar_one()
    if not assigned and not (ctx.scope_of("task.edit") in ("team", "all") and _can_edit(ctx, task)):
        raise forbidden("You can only log time on tasks assigned to you")
    return task


@router.get("/time-entries")
def list_time_entries(
    task: uuid.UUID | None = None, user: uuid.UUID | None = None,
    from_: date | None = Query(default=None, alias="from"), to: date | None = None,
    ctx: Ctx = Depends(require("task.view")), page: Page = Depends(pagination),
):
    stmt = (
        select(TimeEntry, Task.title, User.name).join(Task, Task.id == TimeEntry.task_id)
        .join(User, User.id == TimeEntry.user_id).order_by(TimeEntry.entry_date.desc(), TimeEntry.created_at.desc())
    )
    ids = ctx.visible("task.view")
    if ids is not None:
        owned = owned_project_ids(ctx.db, ctx.me.id)
        stmt = stmt.where(TimeEntry.user_id.in_(ids) | Task.project_id.in_(owned) if owned else TimeEntry.user_id.in_(ids))
    if task:
        stmt = stmt.where(TimeEntry.task_id == task)
    if user:
        stmt = stmt.where(TimeEntry.user_id == user)
    if from_:
        stmt = stmt.where(TimeEntry.entry_date >= from_)
    if to:
        stmt = stmt.where(TimeEntry.entry_date <= to)
    total = ctx.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = ctx.db.execute(stmt.limit(page.limit).offset(page.offset)).all()
    return {"items": [_entry_out(e, t, n) for e, t, n in rows], "total": total, "page": page.page, "limit": page.limit}


class EntryIn(BaseModel):
    task_id: uuid.UUID
    hours: float = Field(gt=0, le=24)
    entry_date: date | None = None
    note: str = Field(default="", max_length=1000)


@router.post("/time-entries", status_code=201)
def create_time_entry(body: EntryIn, ctx: Ctx = Depends(require("task.edit"))):
    task = _loggable_task(ctx, body.task_id)
    today = company_today(ctx.company.timezone)
    day = body.entry_date or today
    if day > today:
        raise bad_request("future_date", "Cannot log time in the future")
    e = TimeEntry(company_id=ctx.company_id, task_id=task.id, user_id=ctx.me.id, hours=Decimal(str(body.hours)), entry_date=day, note=body.note)
    ctx.db.add(e)
    ctx.db.commit()
    return _entry_out(e, task.title, ctx.me.name)


class StartIn(BaseModel):
    task_id: uuid.UUID
    note: str = Field(default="", max_length=1000)


@router.post("/time-entries/start", status_code=201)
def start_timer(body: StartIn, ctx: Ctx = Depends(require("task.edit"))):
    task = _loggable_task(ctx, body.task_id)
    now = datetime.now(UTC)
    e = TimeEntry(
        company_id=ctx.company_id, task_id=task.id, user_id=ctx.me.id, hours=Decimal(0), started_at=now,
        entry_date=now.astimezone(tzinfo(ctx.company.timezone)).date(), note=body.note,
    )
    ctx.db.add(e)
    try:
        ctx.db.commit()
    except IntegrityError:
        ctx.db.rollback()
        raise conflict("timer_running", "Stop your running timer before starting another") from None
    return _entry_out(e, task.title, ctx.me.name)


@router.post("/time-entries/{entry_id}/stop")
def stop_timer(entry_id: uuid.UUID, ctx: Ctx = Depends(require("task.edit"))):
    e = ctx.db.get(TimeEntry, entry_id)
    if not e or e.user_id != ctx.me.id:
        raise not_found("Time entry")
    if not e.started_at or e.stopped_at:
        raise conflict("not_running", "This entry has no running timer")
    now = datetime.now(UTC)
    e.stopped_at = now
    seconds = max((now - e.started_at).total_seconds(), 0)
    e.hours = min(Decimal(str(round(seconds / 3600, 2))), Decimal(24))
    ctx.db.commit()
    return _entry_out(e)


class EntryPatch(BaseModel):
    hours: float | None = Field(default=None, gt=0, le=24)
    entry_date: date | None = None
    note: str | None = Field(default=None, max_length=1000)


def _own_entry(ctx: Ctx, entry_id: uuid.UUID) -> TimeEntry:
    e = ctx.db.get(TimeEntry, entry_id)
    if not e:
        raise not_found("Time entry")
    if e.user_id != ctx.me.id and ctx.scope_of("task.edit") != "all":
        raise forbidden("You can only change your own time entries")
    return e


@router.patch("/time-entries/{entry_id}")
def patch_time_entry(entry_id: uuid.UUID, body: EntryPatch, ctx: Ctx = Depends(require("task.edit"))):
    e = _own_entry(ctx, entry_id)
    if e.started_at and not e.stopped_at:
        raise conflict("timer_running", "Stop the timer before editing this entry")
    data = body.model_dump(exclude_unset=True)
    if data.get("hours") is not None:
        e.hours = Decimal(str(data["hours"]))
    if data.get("entry_date"):
        if data["entry_date"] > company_today(ctx.company.timezone):
            raise bad_request("future_date", "Cannot log time in the future")
        e.entry_date = data["entry_date"]
    if data.get("note") is not None:
        e.note = data["note"]
    ctx.db.commit()
    return _entry_out(e)


@router.delete("/time-entries/{entry_id}", status_code=204)
def delete_time_entry(entry_id: uuid.UUID, ctx: Ctx = Depends(require("task.edit"))):
    ctx.db.delete(_own_entry(ctx, entry_id))
    ctx.db.commit()


# --------------------------------------------------------------------------- daily status
class StatusIn(BaseModel):
    did_today: str = Field(default="", max_length=4000)
    next_up: str = Field(default="", max_length=4000)
    blockers: str = Field(default="", max_length=4000)


def _status_out(s: DailyStatus, name: str | None = None) -> dict:
    return {
        "id": str(s.id), "user_id": str(s.user_id), "user_name": name, "status_date": s.status_date.isoformat(),
        "did_today": s.did_today, "next_up": s.next_up, "blockers": s.blockers, "updated_at": s.updated_at.isoformat(),
    }


@router.get("/daily-status")
def list_daily_status(
    user: uuid.UUID | None = None, from_: date | None = Query(default=None, alias="from"), to: date | None = None,
    ctx: Ctx = Depends(require("status.view")), page: Page = Depends(pagination),
):
    today = company_today(ctx.company.timezone)
    start, end = from_ or today - timedelta(days=7), to or today
    stmt = (
        select(DailyStatus, User.name).join(User, User.id == DailyStatus.user_id)
        .where(DailyStatus.status_date >= start, DailyStatus.status_date <= end)
        .order_by(DailyStatus.status_date.desc(), User.name)
    )
    ids = ctx.visible("status.view")
    if ids is not None:
        stmt = stmt.where(DailyStatus.user_id.in_(ids))
    if user:
        stmt = stmt.where(DailyStatus.user_id == user)
    total = ctx.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = ctx.db.execute(stmt.limit(page.limit).offset(page.offset)).all()
    return {"items": [_status_out(s, n) for s, n in rows], "total": total, "page": page.page, "limit": page.limit}


@router.put("/daily-status/{status_date}")
def put_daily_status(status_date: date, body: StatusIn, ctx: Ctx = Depends(require_any("status.view.own", "status.view.team", "status.view.all"))):
    today = company_today(ctx.company.timezone)
    if status_date > today:
        raise bad_request("future_date", "Cannot write a status for a future day")
    if status_date < today:  # editable until midnight in the company's timezone
        raise ApiError(403, "status_locked", "Daily status can only be edited on the day it belongs to")
    stmt = pg_insert(DailyStatus).values(
        company_id=ctx.company_id, user_id=ctx.me.id, status_date=status_date, **body.model_dump()
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "status_date"], set_={**body.model_dump(), "updated_at": func.now()}
    ).returning(DailyStatus.id)
    sid = ctx.db.execute(stmt).scalar_one()
    ctx.db.commit()
    return _status_out(ctx.db.get(DailyStatus, sid, populate_existing=True), ctx.me.name)
