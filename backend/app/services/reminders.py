"""Reminder messages and who receives them. The wording and the per-role on/off switches are company settings
(companies.reminder_config, JSON); the defaults below are the texts the system always used."""

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, UserRole

# kind -> definition. `time` names the companies column that holds the send time (None: sent when the event happens, or together with another reminder).
KINDS: dict[str, dict[str, Any]] = {
    "morning_plan": {
        "label": "Morning plan", "time": "reminder_morning_time",
        "description": "Weekdays at the morning time, to people who have not posted their plan yet.",
        "placeholders": ["name", "date", "link"],
        "subject": "Share your plan for today",
        "body": "Good morning {name}! Post your morning check-in so the team knows what you are working on:\n{link}",
    },
    "daily_missing": {
        "label": "End-of-day update", "time": "reminder_eod_time",
        "description": "Weekdays at the end-of-day time, to people who have not posted their end-of-day update.",
        "placeholders": ["name", "date", "link"],
        "subject": "Please post your end-of-day update",
        "body": "Hi {name}, no end-of-day update for {date} yet. What did you get done, what's next, any blockers?\n{link}",
    },
    "due": {
        "label": "Tasks due or overdue", "time": "reminder_due_time",
        "description": "Every day at the due time, to the people a task is assigned to (tasks due today or tomorrow, and overdue ones).",
        "placeholders": ["name", "tasks", "link"],
        "subject": "Tasks due soon or overdue",
        "body": "{tasks}\n{link}",
    },
    "team_overdue": {
        "label": "Team overdue", "time": None,
        "description": "Sent together with the due reminder, to team leads, about overdue tasks of their team members.",
        "placeholders": ["name", "tasks", "link"],
        "subject": "Overdue tasks in your team",
        "body": "{tasks}\n{link}",
    },
    "blocker": {
        "label": "Blocked task", "time": None,
        "description": "Immediately when a task is marked as blocked, to the assignees, their team lead and the project members.",
        "placeholders": ["task", "project", "link"],
        "subject": "Blocked: {task}",
        "body": "The task “{task}” in {project} was marked as blocked.\n{link}",
    },
}
MAX_SUBJECT, MAX_BODY = 150, 2000
_TOKEN = re.compile(r"\{(\w+)\}")


def unknown_placeholders(kind: str, *texts: str) -> list[str]:
    allowed = set(KINDS[kind]["placeholders"])
    return sorted({m for t in texts for m in _TOKEN.findall(t) if m not in allowed})


def _config(company: Company, kind: str) -> dict:
    return (company.reminder_config or {}).get(kind) or {}


def _fill(text: str, values: dict[str, str]) -> str:
    return _TOKEN.sub(lambda m: str(values.get(m.group(1), m.group(0))), text)  # only known names are replaced, nothing is evaluated


def render(company: Company, kind: str, **values: str) -> tuple[str, str]:
    """(subject, body) for one reminder: the company's own wording when set, else the default."""
    cfg, d = _config(company, kind), KINDS[kind]
    return _fill(cfg.get("subject") or d["subject"], values), _fill(cfg.get("body") or d["body"], values)


def roles_off(company: Company, kind: str) -> set[str]:
    return set(_config(company, kind).get("roles_off") or [])


def wants(db: Session, company: Company, user_id: uuid.UUID, kind: str) -> bool:
    """False when every role the person has is switched off for this reminder (a person with no role is still reminded)."""
    off = roles_off(company, kind)
    if not off:
        return True
    role_ids = [str(r) for r in db.execute(select(UserRole.role_id).where(UserRole.user_id == user_id)).scalars()]
    return not role_ids or any(r not in off for r in role_ids)
