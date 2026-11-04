"""Facts = every number of a report, computed from the database by code. The AI never produces a number; it only receives these facts
(with people replaced by codes) and writes sentences around them."""

import copy
import re
import string
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ...reports.base import ReportContext
from ...reports.visibility import _shares, query


def build_facts(db: Session, company_name: str, project_ids: list[str] | None, start: date, end: date, today: date) -> dict[str, Any]:
    """`project_ids` None = every project; the caller has already limited it to what the requester may report on."""
    fig = query(ReportContext(db=db, start=start, end=end, today=today, scope_user_ids=None, include_people=True))
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
    return {
        "company": company_name, "period": fig["period"], "projects": projects, "totals": totals, "no_activity": quiet,
        "team_distribution": _shares([(f"{pe['name']} - {p['name']}", pe["hours"]) for p in projects for pe in p.get("people", [])]),
        "hours_by_activity": _shares(list(by_type.items())),
    }


def person_names(facts: dict[str, Any]) -> list[str]:
    return sorted({n for p in facts["projects"] for n in [*(p.get("owners") or []), *(x["name"] for x in p.get("people", []))]}, key=len, reverse=True)


def llm_view(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """A copy of the facts for the model with every person replaced by a code ("Person A"), and the code -> name map for the way back."""
    names = person_names(facts)
    codes = {n: f"Person {string.ascii_uppercase[i] if i < 26 else i + 1}" for i, n in enumerate(sorted(names))}
    pattern = re.compile("|".join(re.escape(n) for n in names)) if names else None

    def walk(o: Any) -> Any:
        if isinstance(o, str):
            return pattern.sub(lambda m: codes[m.group(0)], o) if pattern else o
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o

    view = walk(copy.deepcopy({k: v for k, v in facts.items() if k != "company"}))
    for p in view["projects"]:
        p.pop("id", None)
    return view, {v: k for k, v in codes.items()}


def restore(text_: str, back: dict[str, str]) -> str:
    """Put real names back into model output (the model was told to keep the codes)."""
    for code in sorted(back, key=len, reverse=True):
        text_ = text_.replace(code, back[code])
    return text_
