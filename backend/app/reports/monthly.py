from datetime import date, timedelta

from sqlalchemy import text

from .base import ReportContext, ReportDef, month_bounds, register
from .common import TASK_FILTER, TIME_FILTER, completed_in, hours_in, previous_period, summary_figures


def query(rc: ReportContext) -> dict:
    figures = summary_figures(rc)
    prev_start, prev_end = previous_period(rc.start, rc.end)
    prev_hours, prev_done = hours_in(rc, prev_start, prev_end), completed_in(rc, prev_start, prev_end)
    figures["comparison"] = {
        "previous_period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        "hours_previous": prev_hours, "tasks_completed_previous": prev_done,
        "hours_change": round(figures["totals"]["hours"] - prev_hours, 2),
        "tasks_completed_change": figures["totals"]["tasks_completed"] - prev_done,
    }
    weeks = rc.db.execute(
        text(f"""
        SELECT w.week_start,
          COALESCE((SELECT sum(e.hours) FROM time_entries e JOIN tasks t ON t.id = e.task_id
                    WHERE e.entry_date BETWEEN w.week_start AND w.week_start + 6 AND {TIME_FILTER}
                      AND (CAST(:project AS uuid) IS NULL OR t.project_id = CAST(:project AS uuid))
                      AND (CAST(:client AS uuid) IS NULL OR t.project_id IN (SELECT id FROM projects WHERE client_id = CAST(:client AS uuid)))), 0) AS hours,
          (SELECT count(*) FROM tasks t WHERE t.completed_at::date BETWEEN w.week_start AND w.week_start + 6 AND {TASK_FILTER}) AS completed
        FROM (SELECT generate_series(date_trunc('week', CAST(:from AS date))::date, :to, interval '7 days')::date AS week_start) w
        ORDER BY w.week_start"""), rc.params).all()
    figures["weeks"] = [{"week_start": w.week_start.isoformat(), "hours": round(float(w.hours), 2), "tasks_completed": w.completed} for w in weeks]
    return figures


def default_period(today: date) -> tuple[date, date]:
    first, last = month_bounds(today)
    return first, min(last, today + timedelta(days=0))


REPORT = register(ReportDef(
    key="monthly", title="Monthly report", required_permission="report.monthly.view",
    query=query, template="monthly.html", default_period=default_period,
))
