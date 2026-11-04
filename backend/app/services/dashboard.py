"""Dashboard payload: task counts by status, hours by project/activity, overdue tasks, blockers,
daily-status coverage. Cached 60 s per company + user + filter set."""

import time
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_CACHE: dict[tuple, tuple[float, dict]] = {}
_TTL = 60.0


def clear_dashboard_cache() -> None:
    _CACHE.clear()


def effective_user_ids(visible: set[uuid.UUID] | None, user: uuid.UUID | None) -> list[uuid.UUID] | None:
    """Intersect my permission scope with an optional ?user= filter. None = no restriction."""
    if user is None:
        return None if visible is None else sorted(visible)
    if visible is not None and user not in visible:
        return []
    return [user]


_OWNED = "t.project_id = ANY(CAST(:owned AS uuid[]))"
# Visible work = (assigned to someone in my scope [and, when filtering on a person outside my scope, in a project I own])
#                OR (inside a project I own, when no person filter is set)
TASK_SCOPE = (
    "(((CAST(:uids AS uuid[]) IS NULL OR t.id IN (SELECT task_id FROM task_assignees WHERE user_id = ANY(CAST(:uids AS uuid[]))))"
    f" AND (NOT :owned_only OR {_OWNED})) OR (:widen AND {_OWNED}))"
)
TASK_ACTIVE_IN_PERIOD = "t.created_at::date <= :to AND (t.completed_at IS NULL OR t.completed_at::date >= :from)"


def dashboard(
    db: Session, company_id: uuid.UUID, me: uuid.UUID, uids: list[uuid.UUID] | None, project: uuid.UUID | None,
    start: date, end: date, today: date, *, owned: list[uuid.UUID] | None = None, owned_only: bool = False,
    widen: bool = False, status_uids: list[uuid.UUID] | None | str = "same",
) -> dict[str, Any]:
    """`owned` = projects I own. `widen`: owners also see everything inside them; `owned_only`: a person filter outside
    my scope is honoured only within my owned projects. Daily-status text is never widened (`status_uids`)."""
    owned = owned or []
    s_uids = uids if status_uids == "same" else status_uids
    key = (company_id, me, tuple(uids) if uids is not None else None, project, start, end, today, tuple(owned), owned_only, widen,
           tuple(s_uids) if isinstance(s_uids, list) else s_uids)
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    p = {"uids": uids, "project": project, "from": start, "to": end, "today": today,
         "owned": owned, "owned_only": owned_only, "widen": widen, "status_uids": s_uids}
    proj_t = "(CAST(:project AS uuid) IS NULL OR t.project_id = CAST(:project AS uuid))"

    # 1) tasks ------------------------------------------------------------------------------
    counts = db.execute(
        text(f"""SELECT t.status, count(*) AS n FROM tasks t
                 WHERE {TASK_SCOPE} AND {proj_t} AND {TASK_ACTIVE_IN_PERIOD} GROUP BY t.status"""), p,
    ).all()
    by_status = {s: 0 for s in ("todo", "in_progress", "blocked", "in_review", "done")}
    by_status.update({r.status: r.n for r in counts})

    def task_list(extra: str, order: str) -> list[dict]:
        rows = db.execute(
            text(f"""SELECT t.id, t.title, t.priority, t.due_date, t.status, pr.name AS project,
                            (SELECT string_agg(u.name, ', ' ORDER BY u.name) FROM task_assignees a
                               JOIN users u ON u.id = a.user_id WHERE a.task_id = t.id) AS assignees
                     FROM tasks t JOIN projects pr ON pr.id = t.project_id
                     WHERE {TASK_SCOPE} AND {proj_t} AND {extra} ORDER BY {order} LIMIT 10"""), p,
        ).all()
        return [
            {"id": str(r.id), "title": r.title, "priority": r.priority, "status": r.status, "project": r.project,
             "due_date": r.due_date.isoformat() if r.due_date else None, "assignees": r.assignees or ""}
            for r in rows
        ]

    overdue_total = db.execute(
        text(f"SELECT count(*) FROM tasks t WHERE {TASK_SCOPE} AND {proj_t} AND t.due_date < :today AND t.status <> 'done'"), p
    ).scalar_one()
    blocked_total = db.execute(
        text(f"SELECT count(*) FROM tasks t WHERE {TASK_SCOPE} AND {proj_t} AND t.is_blocked"), p
    ).scalar_one()
    overdue = task_list("t.due_date < :today AND t.status <> 'done'", "t.due_date ASC")
    blockers = task_list("t.is_blocked", "t.updated_at DESC")

    # 2) time entries -----------------------------------------------------------------------
    te_scope = (
        "(((CAST(:uids AS uuid[]) IS NULL OR e.user_id = ANY(CAST(:uids AS uuid[]))) AND (NOT :owned_only OR " + _OWNED + "))"
        " OR (:widen AND " + _OWNED + "))"
    )
    te_where = f"e.entry_date BETWEEN :from AND :to AND {te_scope} AND {proj_t}"
    hours_by_project = [
        {"project": r.name, "hours": float(r.h)}
        for r in db.execute(
            text(f"""SELECT pr.name, sum(e.hours) AS h FROM time_entries e JOIN tasks t ON t.id = e.task_id
                     JOIN projects pr ON pr.id = t.project_id WHERE {te_where} GROUP BY pr.name ORDER BY h DESC"""), p)
    ]
    hours_by_activity = [
        {"activity_type": r.activity_type, "hours": float(r.h)}
        for r in db.execute(
            text(f"""SELECT t.activity_type, sum(e.hours) AS h FROM time_entries e JOIN tasks t ON t.id = e.task_id
                     WHERE {te_where} GROUP BY t.activity_type ORDER BY h DESC"""), p)
    ]
    hours_by_day = [
        {"date": r.d.isoformat(), "hours": float(r.h)}
        for r in db.execute(
            text(f"""SELECT e.entry_date AS d, sum(e.hours) AS h FROM time_entries e JOIN tasks t ON t.id = e.task_id
                     WHERE {te_where} GROUP BY e.entry_date ORDER BY e.entry_date"""), p)
    ]

    # 3) daily status -----------------------------------------------------------------------
    ds_scope = "(CAST(:status_uids AS uuid[]) IS NULL OR d.user_id = ANY(CAST(:status_uids AS uuid[])))"
    expected = db.execute(
        text("SELECT count(*) FROM users u WHERE u.is_active AND (CAST(:status_uids AS uuid[]) IS NULL OR u.id = ANY(CAST(:status_uids AS uuid[])))"), p
    ).scalar_one()
    submitted = db.execute(
        text(f"SELECT count(*) FROM daily_status d WHERE d.status_date = :today AND {ds_scope}"), p
    ).scalar_one()
    status_blockers = [
        {"user": r.name, "date": r.status_date.isoformat(), "text": r.blockers}
        for r in db.execute(
            text(f"""SELECT u.name, d.status_date, d.blockers FROM daily_status d JOIN users u ON u.id = d.user_id
                     WHERE d.status_date BETWEEN :from AND :to AND d.blockers <> '' AND {ds_scope}
                     ORDER BY d.status_date DESC LIMIT 10"""), p)
    ]

    payload = {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "tasks_by_status": by_status,
        "total_tasks": sum(by_status.values()),
        "overdue_count": overdue_total, "blocked_count": blocked_total,
        "total_hours": round(sum(h["hours"] for h in hours_by_project), 2),
        "hours_by_project": hours_by_project, "hours_by_activity": hours_by_activity, "hours_by_day": hours_by_day,
        "overdue_tasks": overdue, "blockers": blockers,
        "daily_status": {"expected": expected, "submitted_today": submitted, "blockers": status_blockers},
    }
    if len(_CACHE) > 500:
        _CACHE.clear()
    _CACHE[key] = (now + _TTL, payload)
    return payload


def default_range(today: date) -> tuple[date, date]:
    return today - timedelta(days=29), today
