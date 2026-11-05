"""Read tools for the assistant: thin, typed wrappers over the same tables the dashboard and reports use. Every tool filters by the CALLER's own
permission scope (never by anything the model says), returns at most 50 rows with their ids, a total count, an as-of time and a structured error
instead of raising. Daily-status text, comments, performance data and other tenants' data are never tool results."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ...perms import best_scope
from ...services.access import owned_project_ids, visible_users
from ...services.dashboard import TASK_ACTIVE_IN_PERIOD, TASK_SCOPE

MAX_ROWS = 50
IN_PROGRESS = ("in_progress", "in_review", "testing", "blocked")


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class ToolCtx:
    db: Session
    user_id: uuid.UUID
    perms: frozenset[str]
    today: date

    def scope_params(self, mine_only: bool = False) -> dict[str, Any]:
        """Task visibility = the caller's task.view scope, widened to every task inside projects they own."""
        scope, ids = visible_users(self.db, self.user_id, self.perms, "task.view")
        if scope is None:
            raise ToolError("permission.denied", "You do not have access to task data.")
        if mine_only:
            ids = {self.user_id}
        return {"uids": None if ids is None else sorted(ids), "owned": [] if mine_only else owned_project_ids(self.db, self.user_id), "owned_only": False, "widen": not mine_only}

    def scope_name(self) -> str:
        return best_scope(self.perms, "task.view") or "none"


def _project_filter(args: dict[str, Any], p: dict[str, Any]) -> str:
    pid = args.get("project_id")
    if pid:
        try:
            p["project"] = uuid.UUID(str(pid))
        except ValueError:
            raise ToolError("invalid.project_id", "project_id is not a valid id.") from None
        return "t.project_id = CAST(:project AS uuid)"
    p["project"] = None
    return "CAST(:project AS uuid) IS NULL"


def _days(args: dict[str, Any], default: int, top: int = 90) -> int:
    try:
        n = int(args.get("days", default))
    except (TypeError, ValueError):
        raise ToolError("invalid.days", "days must be a whole number.") from None
    return max(1, min(n, top))


def _wrap(tc: ToolCtx, name: str, rows: list[dict], total: int, **extra: Any) -> dict[str, Any]:
    return {"tool": name, "as_of": datetime.now(UTC).isoformat(timespec="minutes"), "scope": tc.scope_name(), "total": total, "returned": len(rows), "rows": rows, **extra}


def get_project_figures(tc: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    p = tc.scope_params()
    days = _days(args, 7)
    start, end = tc.today - timedelta(days=days - 1), tc.today
    p.update({"from": start, "to": end, "today": tc.today})
    proj = _project_filter(args, p)
    rows = tc.db.execute(text(f"""
        SELECT pr.id, pr.name, count(*) planned, count(*) FILTER (WHERE t.status = 'done') completed,
               count(*) FILTER (WHERE t.status = ANY(:wip)) in_progress, count(*) FILTER (WHERE t.status = 'todo') pending,
               count(*) FILTER (WHERE t.status = 'blocked') blocked,
               count(*) FILTER (WHERE t.status <> 'done' AND t.due_date < :today) overdue
        FROM tasks t JOIN projects pr ON pr.id = t.project_id
        WHERE {TASK_SCOPE} AND {proj} AND {TASK_ACTIVE_IN_PERIOD} GROUP BY pr.id, pr.name ORDER BY pr.name"""), {**p, "wip": list(IN_PROGRESS)}).all()
    hours = {
        r.project_id: float(r.h) for r in tc.db.execute(text("""
            SELECT t.project_id, sum(e.hours) h FROM time_entries e JOIN tasks t ON t.id = e.task_id
            WHERE e.entry_date BETWEEN :from AND :to AND (CAST(:uids AS uuid[]) IS NULL OR e.user_id = ANY(CAST(:uids AS uuid[]))
                  OR t.project_id = ANY(CAST(:owned AS uuid[]))) GROUP BY t.project_id"""), p)
    }
    out = [{"project_id": str(r.id), "name": r.name, "planned": r.planned, "completed": r.completed, "in_progress": r.in_progress, "pending": r.pending,
            "blocked": r.blocked, "overdue": r.overdue, "progress_pct": round(r.completed / r.planned * 100) if r.planned else 0, "hours": round(hours.get(r.id, 0.0), 2)}
           for r in rows]
    tot = {k: sum(x[k] for x in out) for k in ("planned", "completed", "in_progress", "pending", "blocked", "overdue")}
    tot["hours"] = round(sum(x["hours"] for x in out), 2)
    tot["progress_pct"] = round(tot["completed"] / tot["planned"] * 100) if tot["planned"] else 0
    return _wrap(tc, "get_project_figures", out[:MAX_ROWS], len(out), period={"start": start.isoformat(), "end": end.isoformat()}, days=days, totals=tot)


def get_overdue_and_blocked(tc: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    p = tc.scope_params()
    p["today"] = tc.today
    proj = _project_filter(args, p)
    where = f"{TASK_SCOPE} AND {proj} AND t.status <> 'done' AND (t.status = 'blocked' OR t.due_date < :today)"
    total = tc.db.execute(text(f"SELECT count(*) FROM tasks t WHERE {where}"), p).scalar_one()
    rows = tc.db.execute(text(f"""
        SELECT t.id, t.title, t.status, t.due_date, pr.name AS project,
               (SELECT string_agg(u.name, ', ' ORDER BY u.name) FROM task_assignees a JOIN users u ON u.id = a.user_id WHERE a.task_id = t.id) AS assignees
        FROM tasks t JOIN projects pr ON pr.id = t.project_id WHERE {where}
        ORDER BY t.due_date NULLS LAST, t.title LIMIT :lim"""), {**p, "lim": MAX_ROWS}).all()
    out = [{"task_id": str(r.id), "title": r.title, "project": r.project, "status": r.status, "due_date": r.due_date.isoformat() if r.due_date else None,
            "days_late": (tc.today - r.due_date).days if r.due_date and r.due_date < tc.today else 0, "assignees": r.assignees or "nobody"} for r in rows]
    return _wrap(tc, "get_overdue_and_blocked", out, total)


def get_upcoming(tc: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    days = _days(args, 7, 30)
    p = tc.scope_params(mine_only=bool(args.get("mine_only")))
    p.update({"today": tc.today, "until": tc.today + timedelta(days=days)})
    where = f"{TASK_SCOPE} AND t.status <> 'done' AND t.due_date BETWEEN :today AND :until"
    total = tc.db.execute(text(f"SELECT count(*) FROM tasks t WHERE {where}"), p).scalar_one()
    rows = tc.db.execute(text(f"""
        SELECT t.id, t.title, t.status, t.due_date, pr.name AS project FROM tasks t JOIN projects pr ON pr.id = t.project_id
        WHERE {where} ORDER BY t.due_date, t.title LIMIT :lim"""), {**p, "lim": MAX_ROWS}).all()
    out = [{"task_id": str(r.id), "title": r.title, "project": r.project, "status": r.status, "due_date": r.due_date.isoformat()} for r in rows]
    return _wrap(tc, "get_upcoming", out, total, window_days=days)


def get_effort_by_activity(tc: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    days = _days(args, 7)
    p = tc.scope_params()
    p.update({"from": tc.today - timedelta(days=days - 1), "to": tc.today})
    rows = tc.db.execute(text("""
        SELECT t.activity_type, sum(e.hours) h FROM time_entries e JOIN tasks t ON t.id = e.task_id
        WHERE e.entry_date BETWEEN :from AND :to AND (CAST(:uids AS uuid[]) IS NULL OR e.user_id = ANY(CAST(:uids AS uuid[]))
              OR t.project_id = ANY(CAST(:owned AS uuid[]))) GROUP BY t.activity_type ORDER BY h DESC"""), p).all()
    out = [{"activity": r.activity_type, "hours": round(float(r.h), 2)} for r in rows]
    return _wrap(tc, "get_effort_by_activity", out[:MAX_ROWS], len(out), period={"start": p["from"].isoformat(), "end": p["to"].isoformat()}, days=days, total_hours=round(sum(x["hours"] for x in out), 2))


def get_checkin_completion(tc: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    scope, ids = visible_users(tc.db, tc.user_id, tc.perms, "status.view")
    if scope is None:
        raise ToolError("permission.denied", "You do not have access to daily check-ins.")
    day = tc.today
    if args.get("date"):
        try:
            day = date.fromisoformat(str(args["date"]))
        except ValueError:
            raise ToolError("invalid.date", "date must look like 2026-11-04.") from None
    p = {"uids": None if ids is None else sorted(ids), "day": day}
    rows = tc.db.execute(text("""
        SELECT u.name, d.morning_at IS NOT NULL AS plan, d.eod_at IS NOT NULL AS eod, coalesce(d.blockers, '') <> '' AS blocked
        FROM users u LEFT JOIN daily_status d ON d.user_id = u.id AND d.status_date = :day
        WHERE u.is_active AND (CAST(:uids AS uuid[]) IS NULL OR u.id = ANY(CAST(:uids AS uuid[]))) ORDER BY u.name"""), p).all()
    missing_plan = [r.name for r in rows if not r.plan]
    missing_eod = [r.name for r in rows if not r.eod]
    flagged = [r.name for r in rows if r.blocked]  # who flagged a blocker; the text itself is never returned
    return _wrap(tc, "get_checkin_completion", [], len(rows), date=day.isoformat(), expected=len(rows), posted_plan=len(rows) - len(missing_plan), posted_eod=len(rows) - len(missing_eod),
                 missing_plan=missing_plan[:MAX_ROWS], missing_eod=missing_eod[:MAX_ROWS], flagged_blockers=flagged[:MAX_ROWS], scope=scope)


def explain_progress(tc: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    p = tc.scope_params()
    p["today"] = tc.today
    proj = _project_filter(args, p)
    if not args.get("project_id"):
        raise ToolError("missing.project_id", "Say which project to explain (project_id).")
    counts = tc.db.execute(text(f"SELECT t.status, count(*) n FROM tasks t WHERE {TASK_SCOPE} AND {proj} GROUP BY t.status"), p).all()
    if not counts:
        raise ToolError("not_found", "No tasks you can see in that project.")
    planned = sum(r.n for r in counts)
    done = sum(r.n for r in counts if r.status == "done")
    open_rows = tc.db.execute(text(f"""
        SELECT t.id, t.title, t.status, t.due_date FROM tasks t WHERE {TASK_SCOPE} AND {proj} AND t.status <> 'done'
        ORDER BY t.due_date NULLS LAST, t.title LIMIT :lim"""), {**p, "lim": MAX_ROWS}).all()
    name = tc.db.execute(text("SELECT name FROM projects WHERE id = CAST(:project AS uuid)"), p).scalar_one_or_none()
    rows = [{"task_id": str(r.id), "title": r.title, "status": r.status, "due_date": r.due_date.isoformat() if r.due_date else None} for r in open_rows]
    return _wrap(tc, "explain_progress", rows, planned - done, project=name, project_id=str(args["project_id"]), planned=planned, completed=done,
                 progress_pct=round(done / planned * 100) if planned else 0, formula="progress % = completed tasks / all tasks in the project",
                 status_counts={r.status: r.n for r in counts})


@dataclass(frozen=True)
class Tool:
    fn: Any
    doc: str
    needs: str  # permission base: task.view | status.view


TOOLS: dict[str, Tool] = {
    "get_project_figures": Tool(get_project_figures, 'args: {"project_id": optional, "days": 1-90, default 7}. Per project: planned/completed/in_progress/pending/blocked/overdue tasks, progress %, hours.', "task.view"),
    "get_overdue_and_blocked": Tool(get_overdue_and_blocked, 'args: {"project_id": optional}. Tasks that are overdue or blocked, with project, due date, days late and assignees.', "task.view"),
    "get_upcoming": Tool(get_upcoming, 'args: {"days": 1-30, default 7, "mine_only": true/false}. Open tasks due in the next days.', "task.view"),
    "get_effort_by_activity": Tool(get_effort_by_activity, 'args: {"days": 1-90, default 7}. Logged hours by activity type.', "task.view"),
    "get_checkin_completion": Tool(get_checkin_completion, 'args: {"date": optional YYYY-MM-DD, default today}. Who posted the morning plan / end-of-day update, who is missing, who flagged a blocker (names only).', "status.view"),
    "explain_progress": Tool(explain_progress, 'args: {"project_id": required}. Why a project is at its progress %: the formula, status counts and the open tasks.', "task.view"),
}


def available(perms: frozenset[str]) -> dict[str, Tool]:
    """The tool list the model sees: only tools whose permission the caller holds (filtered BEFORE the model sees anything)."""
    return {n: t for n, t in TOOLS.items() if best_scope(perms, t.needs)}


def run(name: str, args: dict[str, Any], tc: ToolCtx) -> dict[str, Any]:
    """Executes one tool with a re-check of its permission. Never raises: errors come back as {"error": {code, message}}."""
    tool = available(tc.perms).get(name)
    if tool is None:
        return {"tool": name, "error": {"code": "unknown_tool", "message": f"No tool called {name} is available to you."}}
    try:
        return tool.fn(tc, args if isinstance(args, dict) else {})
    except ToolError as e:
        return {"tool": name, "error": {"code": e.code, "message": e.message}}
