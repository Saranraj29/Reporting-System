"""Project visibility report: per project the sprint-style numbers (planned / completed / in progress / pending), the
activities and deliverables of the period, the effort split by activity type, plus (internal reports only) project owners and
the effort per person. Every number is computed here; the AI only writes the sentences (sprint goal, workflow stages,
key achievement) and never sees names."""

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from .base import ReportContext, ReportDef, month_bounds, register
from .common import _CLIENT, _PROJ, TASK_FILTER, TIME_FILTER

ACTIVE = "t.created_at::date <= :to AND (t.completed_at IS NULL OR t.completed_at::date >= :from)"
IN_PROGRESS = {"in_progress", "in_review", "testing", "blocked"}


def _shares(items: list[tuple[str, float]]) -> list[dict[str, Any]]:
    """[(label, weight)] -> [{label, value, pct}] with percentages that add up to exactly 100."""
    items = [(k, v) for k, v in items if v > 0]
    total = sum(v for _, v in items)
    if not total:
        return []
    raw = [(k, v, v / total * 100) for k, v in items]
    pcts = [int(r[2]) for r in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i][2] - pcts[i], reverse=True)[: 100 - sum(pcts)]:
        pcts[i] += 1  # largest remainder method
    return [{"label": k, "value": round(v, 2), "pct": p} for (k, v, _), p in zip(raw, pcts, strict=True)]


def query(rc: ReportContext) -> dict[str, Any]:
    db, p = rc.db, rc.params
    projects = {
        r.id: {"name": r.name, "client": r.client}
        for r in db.execute(text("SELECT pr.id, pr.name, c.name AS client FROM projects pr LEFT JOIN clients c ON c.id = pr.client_id"))
    }
    tasks = db.execute(
        text(f"""SELECT t.project_id, t.title, t.status, t.activity_type, t.due_date FROM tasks t
                 WHERE {TASK_FILTER} AND {ACTIVE} ORDER BY t.completed_at NULLS LAST, t.created_at LIMIT 3000"""), p).all()
    effort = db.execute(
        text(f"""SELECT t.project_id, t.activity_type, u.name AS person, sum(e.hours) AS h
                 FROM time_entries e JOIN tasks t ON t.id = e.task_id JOIN users u ON u.id = e.user_id
                 WHERE e.entry_date BETWEEN :from AND :to AND {TIME_FILTER} AND {_PROJ} AND {_CLIENT}
                 GROUP BY t.project_id, t.activity_type, u.name"""), p).all()
    owners: dict[Any, list[str]] = defaultdict(list)
    if rc.include_people:
        for r in db.execute(text("""SELECT pm.project_id, u.name FROM project_members pm JOIN users u ON u.id = pm.user_id
                                    WHERE pm.is_owner ORDER BY u.name""")):
            owners[r.project_id].append(r.name)

    by_project: dict[Any, dict[str, Any]] = {}
    for t in tasks:
        info = projects.get(t.project_id)
        if info is None:
            continue
        pr = by_project.setdefault(t.project_id, {
            **info, "id": str(t.project_id), "status_counts": defaultdict(int), "activities": [], "deliverables": [], "by_type": defaultdict(int),
            "blocked": [], "overdue": [], "upcoming": [],
        })
        pr["status_counts"][t.status] += 1
        pr["by_type"][t.activity_type] += 1
        pr["activities"].append({"title": t.title, "status": t.status})
        if t.status == "done":
            pr["deliverables"].append(t.title)
        else:
            if t.status == "blocked":
                pr["blocked"].append(t.title)
            if t.due_date and t.due_date < min(rc.end, rc.today):
                pr["overdue"].append({"title": t.title, "due_date": t.due_date.isoformat(), "days_late": (min(rc.end, rc.today) - t.due_date).days})
            elif t.due_date and rc.end <= t.due_date <= rc.end + timedelta(days=14):
                pr["upcoming"].append({"title": t.title, "due_date": t.due_date.isoformat()})

    hours_by_type: dict[Any, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    hours_by_person: dict[Any, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in effort:
        hours_by_type[r.project_id][r.activity_type] += float(r.h)
        hours_by_person[r.project_id][r.person] += float(r.h)

    out = []
    for pid, pr in sorted(by_project.items(), key=lambda kv: kv[1]["name"].lower()):
        c = pr["status_counts"]
        planned = sum(c.values())
        done = c["done"]
        todo = c["todo"]
        wip = sum(n for s, n in c.items() if s in IN_PROGRESS)
        hrs = hours_by_type.get(pid, {})
        entry: dict[str, Any] = {
            "id": pr["id"], "name": pr["name"], "client": pr["client"],
            "blocked": pr["blocked"][:15], "overdue": pr["overdue"][:15], "upcoming": sorted(pr["upcoming"], key=lambda x: x["due_date"])[:15],
            "status": "completed" if planned and done == planned else "in_progress",
            "planned": planned, "completed": done, "in_progress": wip, "pending": todo,
            "progress": round(done / planned * 100) if planned else 0,
            "activities": pr["activities"][:40], "deliverables": pr["deliverables"][:40],
            "hours": round(sum(hrs.values()), 2),
            # effort split by activity type; falls back to the task count when nobody logged time
            "work_distribution": _shares(list(hrs.items())) or _shares([(k, float(v)) for k, v in pr["by_type"].items()]),
        }
        if rc.include_people:
            entry["owners"] = owners.get(pid, [])
            entry["people"] = [{"name": k, "hours": round(v, 2)} for k, v in sorted(hours_by_person.get(pid, {}).items(), key=lambda kv: -kv[1])]
        out.append(entry)

    figures: dict[str, Any] = {
        "period": {"start": rc.start.isoformat(), "end": rc.end.isoformat()},
        "totals": {
            "projects": len(out), "planned": sum(x["planned"] for x in out), "completed": sum(x["completed"] for x in out),
            "in_progress": sum(x["in_progress"] for x in out), "pending": sum(x["pending"] for x in out),
            "hours": round(sum(x["hours"] for x in out), 2),
        },
        "projects": out,
    }
    if rc.include_people:
        figures["team_distribution"] = _shares([(f"{pe['name']} - {x['name']}", pe["hours"]) for x in out for pe in x.get("people", [])])
    return figures


def default_period(today: date) -> tuple[date, date]:
    first, last = month_bounds(today)
    return first, min(last, today)


REPORT = register(ReportDef(
    key="visibility", title="Project visibility report", required_permission="report.visibility.view",
    query=query, template="visibility.html", default_period=default_period, client_safe=True,
))
