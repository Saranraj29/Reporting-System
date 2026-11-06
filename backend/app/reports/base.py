"""A base report is one small module: key, title, required permission, query() -> figures, template.
`figures` is plain JSON and the only thing exporters and the AI step ever see."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session


@dataclass
class ReportContext:
    db: Session
    start: date
    end: date
    today: date
    scope_user_ids: list[uuid.UUID] | None = None  # None = whole company
    project_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None  # only the projects of this team
    include_people: bool = True  # False for client-facing reports: no names, no individual figures

    @property
    def uids(self) -> list[uuid.UUID] | None:
        if self.user_id is None:
            return self.scope_user_ids
        if self.scope_user_ids is not None and self.user_id not in self.scope_user_ids:
            return []
        return [self.user_id]

    @property
    def params(self) -> dict:
        return {
            "uids": self.uids, "project": self.project_id, "client": self.client_id, "team": self.team_id,
            "from": self.start, "to": self.end, "today": self.today,
        }


@dataclass(frozen=True)
class ReportDef:
    key: str
    title: str
    required_permission: str  # base key, e.g. "report.weekly.view" (scope .team/.all is resolved by the guard)
    query: Callable[[ReportContext], dict]
    template: str  # Jinja template file in reports/templates
    default_period: Callable[[date], tuple[date, date]]
    client_safe: bool = True  # may be used for client-facing (AI) reports
    people: bool = False  # whole report is about individuals


REGISTRY: dict[str, ReportDef] = {}


def register(defn: ReportDef) -> ReportDef:
    REGISTRY[defn.key] = defn
    return defn


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def month_bounds(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)

