"""Quick-action cards per page and their code-owned workflows: a fixed typed request, tools called by code, sentences from templates. They need no model,
so they work when the AI service is down; the numbers are grounded by construction (and checked by the same verifier in tests)."""

from typing import Any

from . import tools
from .tools import ToolCtx

# page -> cards (id, title, subtitle, phase). Phase 2/3 cards are shown greyed "coming soon" until their capability exists.
CARDS: dict[str, list[dict[str, Any]]] = {
    "dashboard": [
        {"id": "explain_week", "title": "Explain this week's numbers", "subtitle": "What moved in the last 7 days", "phase": 1},
        {"id": "overdue_why", "title": "What is overdue, and why?", "subtitle": "Overdue and blocked work", "phase": 1},
        {"id": "weekly_brief", "title": "Draft this week's brief", "subtitle": "A short digest for managers", "phase": 2},
    ],
    "tasks": [
        {"id": "at_risk", "title": "Which tasks are at risk?", "subtitle": "Overdue, blocked or due soon", "phase": 1},
        {"id": "project_summary", "title": "Summarise this project for a manager", "subtitle": "Progress, risks and hours", "phase": 1},
        {"id": "replan_overdue", "title": "Re-plan the overdue tasks", "subtitle": "Suggest new dates", "phase": 3},
    ],
    "my-day": [
        {"id": "my_due", "title": "What is due from me this week?", "subtitle": "Your open tasks by due date", "phase": 1},
        {"id": "plan_day", "title": "Plan my day from my open tasks", "subtitle": "A suggested order", "phase": 3},
        {"id": "missed_checkin", "title": "I missed yesterday's check-in", "subtitle": "Draft it for me", "phase": 3},
    ],
    "check-ins": [
        {"id": "who_missing", "title": "Who is missing today?", "subtitle": "Morning plan and end-of-day update", "phase": 1},
        {"id": "todays_blockers", "title": "Summarise today's blockers", "subtitle": "Who flagged a blocker", "phase": 1},
        {"id": "remind_missing", "title": "Remind the people who are missing", "subtitle": "Send a reminder", "phase": 3},
    ],
}
ENABLED_PHASES = {1}
REQUEST_TEXT = {c["id"]: c["title"] for cards in CARDS.values() for c in cards}
LABEL = {
    "get_project_figures": "Project figures", "get_overdue_and_blocked": "Overdue and blocked tasks", "get_upcoming": "Upcoming tasks",
    "get_effort_by_activity": "Logged hours", "get_checkin_completion": "Check-ins", "explain_progress": "Project progress",
}


def cards_for(page: str) -> list[dict[str, Any]]:
    return [{**c, "enabled": c["phase"] in ENABLED_PHASES} for c in CARDS.get(page, [])]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _need(call: dict[str, Any]) -> dict[str, Any] | None:
    return call if "error" not in call else None


def _error_sentence(call: dict[str, Any]) -> list[str]:
    return [call["error"]["message"]]


def _titles(rows: list[dict], limit: int = 5) -> list[dict]:
    return rows[:limit]


def explain_week(tc: ToolCtx, ctx: dict) -> tuple[list[str], list[dict]]:
    r = tools.run("get_project_figures", {"days": 7}, tc)
    if "error" in r:
        return _error_sentence(r), [r]
    t = r["totals"]
    if not r["rows"]:
        return ["There is no task activity in your scope in the last 7 days."], [r]
    s = [f"In the last {r['days']} days your scope has {_plural(t['planned'], 'task')} in {_plural(r['total'], 'project')}: {t['completed']} completed ({t['progress_pct']}%), "
         f"{t['in_progress']} in progress and {t['pending']} pending."]
    if t["hours"]:
        s.append(f"{t['hours']:g} hours were logged.")
    best = max(r["rows"], key=lambda x: x["progress_pct"])
    if len(r["rows"]) > 1:
        s.append(f"{best['name']} is furthest along at {best['progress_pct']}%.")
    if t["overdue"] or t["blocked"]:
        s.append(f"{t['overdue']} {'task is' if t['overdue'] == 1 else 'tasks are'} overdue and {t['blocked']} blocked.")
    return s, [r]


def _risk_lines(r: dict, why: bool) -> list[str]:
    rows = r["rows"]
    if not rows:
        return ["Nothing is overdue or blocked in your scope."]
    s = [f"{_plural(r['total'], 'task')} {'is' if r['total'] == 1 else 'are'} overdue or blocked."]
    for x in _titles(rows):
        who = f", assigned to {x['assignees']}" if x["assignees"] != "nobody" else ", with nobody assigned"
        if x["days_late"]:
            s.append(f"“{x['title']}” in {x['project']} is {_plural(x['days_late'], 'day')} overdue ({x['status'].replace('_', ' ')}){who}.")
        else:
            s.append(f"“{x['title']}” in {x['project']} is blocked{who}.")
    if r["total"] > len(_titles(rows)):
        s.append(f"{r['total'] - 5} more are not listed here.")
    if why:
        s.append("The data shows the due date has passed or the status is blocked; it does not record the reason, so the assignees are the ones to ask.")
    return s


def overdue_why(tc: ToolCtx, ctx: dict) -> tuple[list[str], list[dict]]:
    r = tools.run("get_overdue_and_blocked", {"project_id": ctx.get("project_id")}, tc)
    return (_error_sentence(r) if "error" in r else _risk_lines(r, True)), [r]


def at_risk(tc: ToolCtx, ctx: dict) -> tuple[list[str], list[dict]]:
    a = tools.run("get_overdue_and_blocked", {"project_id": ctx.get("project_id")}, tc)
    b = tools.run("get_upcoming", {"days": 3}, tc)
    if "error" in a:
        return _error_sentence(a), [a]
    s = _risk_lines(a, False)
    if "error" not in b:
        if b["rows"]:
            s.append(f"{_plural(b['total'], 'open task')} {'is' if b['total'] == 1 else 'are'} due in the next {b['window_days']} days.")
            s += [f"“{x['title']}” in {x['project']} is due on {x['due_date']} ({x['status'].replace('_', ' ')})." for x in _titles(b["rows"], 3)]
        else:
            s.append(f"Nothing else is due in the next {b['window_days']} days.")
    return s, [a, b]


def project_summary(tc: ToolCtx, ctx: dict) -> tuple[list[str], list[dict]]:
    f = tools.run("get_project_figures", {"days": 14, "project_id": ctx.get("project_id")}, tc)
    if "error" in f:
        return _error_sentence(f), [f]
    if not f["rows"]:
        return ["There is no task activity in your scope for this period."], [f]
    s = []
    for x in f["rows"][:5]:
        s.append(f"{x['name']} is {x['progress_pct']}% complete: {x['completed']} of {_plural(x['planned'], 'task')} done, {x['in_progress']} in progress, {x['pending']} pending, {x['hours']:g} hours logged.")
        if x["overdue"] or x["blocked"]:
            s.append(f"{x['name']} has {x['overdue']} overdue and {x['blocked']} blocked.")
    if f["total"] > 5:
        s.append(f"{f['total'] - 5} more projects are not listed here.")
    return s, [f]


def my_due(tc: ToolCtx, ctx: dict) -> tuple[list[str], list[dict]]:
    r = tools.run("get_upcoming", {"days": 7, "mine_only": True}, tc)
    if "error" in r:
        return _error_sentence(r), [r]
    if not r["rows"]:
        return [f"Nothing assigned to you is due in the next {r['window_days']} days."], [r]
    s = [f"You have {_plural(r['total'], 'open task')} due in the next {r['window_days']} days."]
    s += [f"“{x['title']}” in {x['project']} is due on {x['due_date']} ({x['status'].replace('_', ' ')})." for x in _titles(r["rows"], 8)]
    return s, [r]


def who_missing(tc: ToolCtx, ctx: dict) -> tuple[list[str], list[dict]]:
    r = tools.run("get_checkin_completion", {}, tc)
    if "error" in r:
        return _error_sentence(r), [r]
    s = [f"{r['posted_plan']} of {r['expected']} people have posted a morning plan, and {r['posted_eod']} of {r['expected']} an end-of-day update."]
    if r["missing_plan"]:
        s.append(f"No morning plan yet: {', '.join(r['missing_plan'])}.")
    if r["missing_eod"] and r["missing_eod"] != r["missing_plan"]:
        s.append(f"No end-of-day update yet: {', '.join(r['missing_eod'])}.")
    return s, [r]


def todays_blockers(tc: ToolCtx, ctx: dict) -> tuple[list[str], list[dict]]:
    r = tools.run("get_checkin_completion", {}, tc)
    if "error" in r:
        return _error_sentence(r), [r]
    n = len(r["flagged_blockers"])
    if not n:
        return ["No one has flagged a blocker in today's check-ins."], [r]
    return [f"{_plural(n, 'person')} flagged a blocker today: {', '.join(r['flagged_blockers'])}.", "The blocker text is on the Check-ins page."], [r]


WORKFLOWS = {
    "explain_week": explain_week, "overdue_why": overdue_why, "at_risk": at_risk, "project_summary": project_summary,
    "my_due": my_due, "who_missing": who_missing, "todays_blockers": todays_blockers,
}


