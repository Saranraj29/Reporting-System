from datetime import date, timedelta

from sqlalchemy import text

from .base import ReportContext, ReportDef, month_bounds, register


def working_days(start: date, end: date) -> int:
    return sum(1 for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5)


def query(rc: ReportContext) -> dict:
    available = working_days(rc.start, rc.end) * 8
    rows = rc.db.execute(
        text("""
        SELECT u.name,
          COALESCE(h.hours, 0) AS hours, COALESCE(c.done, 0) AS done, COALESCE(c.with_due, 0) AS with_due,
          COALESCE(c.on_time, 0) AS on_time, c.avg_days,
          COALESCE(o.open_n, 0) AS open_n, COALESCE(o.blocked_n, 0) AS blocked_n
        FROM users u
        LEFT JOIN (SELECT e.user_id, sum(e.hours) AS hours FROM time_entries e JOIN tasks t ON t.id = e.task_id
                   WHERE e.entry_date BETWEEN :from AND :to
                     AND (CAST(:project AS uuid) IS NULL OR t.project_id = CAST(:project AS uuid)) GROUP BY e.user_id) h ON h.user_id = u.id
        LEFT JOIN (SELECT a.user_id, count(*) AS done,
                     count(*) FILTER (WHERE t.due_date IS NOT NULL) AS with_due,
                     count(*) FILTER (WHERE t.due_date IS NOT NULL AND t.completed_at::date <= t.due_date) AS on_time,
                     avg(extract(epoch FROM (t.completed_at - t.created_at)) / 86400.0) AS avg_days
                   FROM tasks t JOIN task_assignees a ON a.task_id = t.id
                   WHERE t.completed_at::date BETWEEN :from AND :to
                     AND (CAST(:project AS uuid) IS NULL OR t.project_id = CAST(:project AS uuid)) GROUP BY a.user_id) c ON c.user_id = u.id
        LEFT JOIN (SELECT a.user_id, count(*) FILTER (WHERE t.status <> 'done') AS open_n,
                     count(*) FILTER (WHERE t.is_blocked) AS blocked_n
                   FROM tasks t JOIN task_assignees a ON a.task_id = t.id
                   WHERE (CAST(:project AS uuid) IS NULL OR t.project_id = CAST(:project AS uuid)) GROUP BY a.user_id) o ON o.user_id = u.id
        WHERE u.is_active AND (CAST(:uids AS uuid[]) IS NULL OR u.id = ANY(CAST(:uids AS uuid[])))
        ORDER BY done DESC, hours DESC, u.name"""), rc.params).all()
    people = [
        {
            "name": r.name, "hours": round(float(r.hours), 2), "tasks_completed": r.done,
            "on_time_rate": round(r.on_time / r.with_due * 100) if r.with_due else None,
            "avg_days_to_complete": round(float(r.avg_days), 1) if r.avg_days is not None else None,
            "utilization": round(float(r.hours) / available * 100) if available else None,
            "open_tasks": r.open_n, "blocked_tasks": r.blocked_n,
        }
        for r in rows
    ]
    total_done = sum(p["tasks_completed"] for p in people)
    return {
        "period": {"start": rc.start.isoformat(), "end": rc.end.isoformat()},
        "available_hours_per_person": available,
        "totals": {
            "people": len(people), "hours": round(sum(p["hours"] for p in people), 2), "tasks_completed": total_done,
        },
        "people": people,
    }


def default_period(today: date) -> tuple[date, date]:
    first, last = month_bounds(today)
    return first, min(last, today)


REPORT = register(ReportDef(
    key="performance", title="Performance report", required_permission="report.performance.view",
    query=query, template="performance.html", default_period=default_period, client_safe=False, people=True,
))
