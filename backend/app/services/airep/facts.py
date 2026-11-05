"""Facts = every number of a report, computed from the database by code. The AI never produces a number; it only receives these facts
(with people replaced by codes) and writes sentences around them."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ...ai.redact import llm_view, person_names, restore  # noqa: F401  (people coding lives in app.ai.redact)
from ...reports.base import ReportContext
from ...reports.visibility import _shares, query


def build_facts(db: Session, company_name: str, project_ids: list[str] | None, start: date, end: date, today: date,
                person_ids: list[str] | None = None) -> dict[str, Any]:
    """`project_ids` None = every project; the caller has already limited it to what the requester may report on.
    `person_ids` None = everyone; otherwise only the work of these people is counted."""
    scope = [uuid.UUID(u) for u in person_ids] if person_ids else None
    fig = query(ReportContext(db=db, start=start, end=end, today=today, scope_user_ids=scope, include_people=True))
    wanted = None if project_ids is None else set(project_ids)
    projects = [p for p in fig["projects"] if wanted is None or p["id"] in wanted]
    names = {str(r.id): r.name for r in db.execute(text("SELECT id, name FROM projects"))}
    quiet = sorted(names[i] for i in (wanted or set()) if i in names and i not in {p["id"] for p in projects})  # selected but no activity
    by_type: dict[str, float] = {}
    for p in projects:
        for d in p["work_distribution"]:
            by_type[d["label"]] = by_type.get(d["label"], 0) + d["value"]
    totals = {k: sum(p[k] for p in projects) for k in ("planned", "completed", "in_progress", "pending")}
    totals.update(projects=len(projects), hours=round(sum(p["hours"] for p in projects), 2))
    people_filter = sorted(r.name for r in db.execute(text("SELECT name FROM users WHERE id = ANY(:ids)"), {"ids": scope})) if scope else []
    return {
        "company": company_name, "period": fig["period"], "projects": projects, "totals": totals, "no_activity": quiet, "people_filter": people_filter,
        "team_distribution": _shares([(f"{pe['name']} - {p['name']}", pe["hours"]) for p in projects for pe in p.get("people", [])]),
        "hours_by_activity": _shares(list(by_type.items())),
    }
