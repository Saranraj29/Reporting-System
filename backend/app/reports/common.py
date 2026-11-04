"""Shared figure builders used by the weekly and monthly reports."""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from .base import ReportContext

_TASK_SCOPE = "(CAST(:uids AS uuid[]) IS NULL OR t.id IN (SELECT task_id FROM task_assignees WHERE user_id = ANY(CAST(:uids AS uuid[]))))"
_PROJ = "(CAST(:project AS uuid) IS NULL OR t.project_id = CAST(:project AS uuid))"
_CLIENT = "(CAST(:client AS uuid) IS NULL OR t.project_id IN (SELECT id FROM projects WHERE client_id = CAST(:client AS uuid)))"
TASK_FILTER = f"{_TASK_SCOPE} AND {_PROJ} AND {_CLIENT}"
TIME_FILTER = "(CAST(:uids AS uuid[]) IS NULL OR e.user_id = ANY(CAST(:uids AS uuid[])))"


def _d(v: date | None) -> str | None:
    return v.isoformat() if v else None


def _r(v: Any) -> float:
    return round(float(v or 0), 2)


def hours_in(rc: ReportContext, start: date, end: date) -> float:
    p = {**rc.params, "from": start, "to": end}
    return _r(rc.db.execute(
        text(f"""SELECT sum(e.hours) FROM time_entries e JOIN tasks t ON t.id = e.task_id
                 WHERE e.entry_date BETWEEN :from AND :to AND {TIME_FILTER} AND {_PROJ} AND {_CLIENT}"""), p).scalar_one())


def completed_in(rc: ReportContext, start: date, end: date) -> int:
    p = {**rc.params, "from": start, "to": end}
    return rc.db.execute(
        text(f"SELECT count(*) FROM tasks t WHERE t.completed_at::date BETWEEN :from AND :to AND {TASK_FILTER}"), p
    ).scalar_one()


def summary_figures(rc: ReportContext) -> dict[str, Any]:
    db, p = rc.db, rc.params
    created = db.execute(text(f"SELECT count(*) FROM tasks t WHERE t.created_at::date BETWEEN :from AND :to AND {TASK_FILTER}"), p).scalar_one()
    open_ = db.execute(text(f"SELECT count(*) FROM tasks t WHERE t.status <> 'done' AND t.created_at::date <= :to AND {TASK_FILTER}"), p).scalar_one()
    blocked = db.execute(text(f"SELECT count(*) FROM tasks t WHERE t.is_blocked AND {TASK_FILTER}"), p).scalar_one()
    overdue = db.execute(
        text(f"SELECT count(*) FROM tasks t WHERE t.due_date < LEAST(:to, :today) AND t.status <> 'done' AND {TASK_FILTER}"), p
    ).scalar_one()

    projects = [
        {
            "project": r.name, "client": r.client, "hours": _r(r.hours),
            "tasks_completed": r.completed, "tasks_open": r.open,
        }
        for r in db.execute(
            text(f"""
            SELECT pr.name, c.name AS client,
              COALESCE((SELECT sum(e.hours) FROM time_entries e JOIN tasks t ON t.id = e.task_id
                        WHERE t.project_id = pr.id AND e.entry_date BETWEEN :from AND :to AND {TIME_FILTER}), 0) AS hours,
              (SELECT count(*) FROM tasks t WHERE t.project_id = pr.id AND t.completed_at::date BETWEEN :from AND :to AND {_TASK_SCOPE}) AS completed,
              (SELECT count(*) FROM tasks t WHERE t.project_id = pr.id AND t.status <> 'done' AND t.created_at::date <= :to AND {_TASK_SCOPE}) AS open
            FROM projects pr LEFT JOIN clients c ON c.id = pr.client_id
            WHERE (CAST(:project AS uuid) IS NULL OR pr.id = CAST(:project AS uuid))
              AND (CAST(:client AS uuid) IS NULL OR pr.client_id = CAST(:client AS uuid))
            ORDER BY hours DESC, pr.name"""), p)
        if r.hours or r.completed or r.open
    ]
    activity = [
        {"activity_type": r.activity_type, "hours": _r(r.h)}
        for r in db.execute(
            text(f"""SELECT t.activity_type, sum(e.hours) AS h FROM time_entries e JOIN tasks t ON t.id = e.task_id
                     WHERE e.entry_date BETWEEN :from AND :to AND {TIME_FILTER} AND {_PROJ} AND {_CLIENT}
                     GROUP BY t.activity_type ORDER BY h DESC"""), p)
    ]
    completed_tasks = [
        {"title": r.title, "project": r.project, "completed_on": _d(r.done), "hours": _r(r.hours)}
        for r in db.execute(
            text(f"""SELECT t.title, pr.name AS project, t.completed_at::date AS done,
                       COALESCE((SELECT sum(hours) FROM time_entries WHERE task_id = t.id), 0) AS hours
                     FROM tasks t JOIN projects pr ON pr.id = t.project_id
                     WHERE t.completed_at::date BETWEEN :from AND :to AND {TASK_FILTER}
                     ORDER BY t.completed_at DESC LIMIT 25"""), p)
    ]
    blockers = [
        {"title": r.title, "project": r.project, "priority": r.priority}
        for r in db.execute(
            text(f"""SELECT t.title, pr.name AS project, t.priority FROM tasks t JOIN projects pr ON pr.id = t.project_id
                     WHERE t.is_blocked AND {TASK_FILTER} ORDER BY t.updated_at DESC LIMIT 15"""), p)
    ]
    overdue_tasks = [
        {"title": r.title, "project": r.project, "due_date": _d(r.due_date), "days_late": (min(rc.end, rc.today) - r.due_date).days}
        for r in db.execute(
            text(f"""SELECT t.title, pr.name AS project, t.due_date FROM tasks t JOIN projects pr ON pr.id = t.project_id
                     WHERE t.due_date < LEAST(:to, :today) AND t.status <> 'done' AND {TASK_FILTER}
                     ORDER BY t.due_date LIMIT 15"""), p)
    ]
    upcoming = [
        {"title": r.title, "project": r.project, "due_date": _d(r.due_date), "status": r.status}
        for r in db.execute(
            text(f"""SELECT t.title, pr.name AS project, t.due_date, t.status FROM tasks t JOIN projects pr ON pr.id = t.project_id
                     WHERE t.status <> 'done' AND t.due_date BETWEEN :to AND CAST(:to AS date) + 14 AND {TASK_FILTER}
                     ORDER BY t.due_date LIMIT 15"""), p)
    ]
    figures: dict[str, Any] = {
        "period": {"start": _d(rc.start), "end": _d(rc.end)},
        "totals": {
            "hours": hours_in(rc, rc.start, rc.end), "tasks_completed": completed_in(rc, rc.start, rc.end),
            "tasks_created": created, "tasks_open": open_, "blocked_tasks": blocked, "overdue_tasks": overdue,
        },
        "projects": projects, "activity": activity, "completed_tasks": completed_tasks,
        "blockers": blockers, "overdue": overdue_tasks, "upcoming": upcoming,
    }
    if rc.include_people:
        figures["people"] = [
            {"name": r.name, "hours": _r(r.hours), "tasks_completed": r.completed}
            for r in db.execute(
                text(f"""
                SELECT u.name,
                  COALESCE((SELECT sum(e.hours) FROM time_entries e JOIN tasks t ON t.id = e.task_id
                            WHERE e.user_id = u.id AND e.entry_date BETWEEN :from AND :to AND {_PROJ} AND {_CLIENT}), 0) AS hours,
                  (SELECT count(*) FROM tasks t JOIN task_assignees a ON a.task_id = t.id
                   WHERE a.user_id = u.id AND t.completed_at::date BETWEEN :from AND :to AND {_PROJ} AND {_CLIENT}) AS completed
                FROM users u WHERE u.is_active AND (CAST(:uids AS uuid[]) IS NULL OR u.id = ANY(CAST(:uids AS uuid[])))
                ORDER BY hours DESC, u.name"""), p)
            if r.hours or r.completed
        ]
        figures.update(check_in_figures(rc))
    return figures


def working_days(start: date, end: date) -> int:
    return sum(1 for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5)


def check_in_figures(rc: ReportContext) -> dict[str, Any]:
    """Morning plan / end-of-day update tracking for the people in scope. Internal reports only: these keys hold the text
    people wrote, so they are stripped before anything goes to an LLM (services/ai.FORBIDDEN_KEYS)."""
    db, p = rc.db, rc.params
    last = min(rc.end, rc.today)
    days = working_days(rc.start, last) if last >= rc.start else 0
    people = db.execute(
        text("""
        SELECT u.id, u.name,
          count(d.id) FILTER (WHERE d.morning_at IS NOT NULL) AS morning_days,
          count(d.id) FILTER (WHERE d.eod_at IS NOT NULL) AS eod_days,
          count(d.id) FILTER (WHERE d.blockers <> '') AS blocker_days
        FROM users u LEFT JOIN daily_status d ON d.user_id = u.id AND d.status_date BETWEEN :from AND :to
        WHERE u.is_active AND (CAST(:uids AS uuid[]) IS NULL OR u.id = ANY(CAST(:uids AS uuid[])))
        GROUP BY u.id, u.name ORDER BY u.name"""), p).all()
    rate = lambda n: round(n / days * 100) if days else None  # noqa: E731
    per_person = [
        {"name": r.name, "working_days": days, "morning_plans": r.morning_days, "eod_updates": r.eod_days,
         "morning_rate": rate(r.morning_days), "eod_rate": rate(r.eod_days), "days_with_blockers": r.blocker_days}
        for r in people
    ]
    entries = [
        {"date": _d(r.status_date), "name": r.name, "morning_plan": r.plan_today, "morning_at": r.morning_at.strftime("%H:%M") if r.morning_at else None,
         "done": r.did_today, "eod_at": r.eod_at.strftime("%H:%M") if r.eod_at else None, "next_up": r.next_up, "blockers": r.blockers}
        for r in db.execute(
            text("""SELECT d.status_date, u.name, d.plan_today, d.morning_at, d.did_today, d.eod_at, d.next_up, d.blockers
                    FROM daily_status d JOIN users u ON u.id = d.user_id
                    WHERE d.status_date BETWEEN :from AND :to AND (CAST(:uids AS uuid[]) IS NULL OR d.user_id = ANY(CAST(:uids AS uuid[])))
                    ORDER BY d.status_date DESC, u.name LIMIT 200"""), p)
    ]
    expected = days * len(people)
    return {
        "check_in_totals": {
            "working_days": days, "people": len(people),
            "morning_plans": sum(x["morning_plans"] for x in per_person), "eod_updates": sum(x["eod_updates"] for x in per_person),
            "morning_rate": round(sum(x["morning_plans"] for x in per_person) / expected * 100) if expected else None,
            "eod_rate": round(sum(x["eod_updates"] for x in per_person) / expected * 100) if expected else None,
        },
        "check_ins": per_person, "check_in_entries": entries,
    }


def previous_period(start: date, end: date) -> tuple[date, date]:
    span = (end - start).days + 1
    return start - timedelta(days=span), start - timedelta(days=1)
