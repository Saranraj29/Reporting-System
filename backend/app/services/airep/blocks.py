"""The block catalog. A report outline is a list of sections; a section is either a BLOCK (a table / chart / KPI row that this code
renders from the facts, so every number is exact) or TEXT (written by the AI from the same facts). New block = one function + one
catalog entry."""

from typing import Any

from ...reports.mdreport import (
    ACTIVITY_STATUS,
    STATUS_LABEL,
    _flow,
    _pie,
    esc,
    fallback_workflow,
    nice_period,
)

# name -> (scope, shown to the user as, what it contains)
CATALOG: dict[str, tuple[str, str, str]] = {
    "header_table": ("per_project", "Project details", "table: period, project, owner, status"),
    "kpi_row": ("per_project", "Task numbers", "table: planned / completed / in progress / pending / progress %"),
    "status_pie": ("per_project", "Status chart", "pie chart of completed / in progress / pending tasks"),
    "workflow": ("per_project", "Workflow", "flow of 3-6 stages the work goes through (stage names written by the AI)"),
    "activities_table": ("per_project", "Activities", "table: every task of the period with its status"),
    "deliverables_table": ("per_project", "Completed deliverables", "table of the tasks completed in the period"),
    "work_pie": ("per_project", "Work distribution", "pie chart of the effort per activity type"),
    "risks_table": ("per_project", "Risks & blockers", "table of blocked and overdue tasks of the project"),
    "upcoming_table": ("per_project", "Coming up", "table of tasks due in the next 14 days"),
    "totals_row": ("overall", "Key metrics", "table: projects, task numbers, progress %, hours"),
    "health_pie": ("overall", "Project health", "pie chart of the progress % of every project"),
    "projects_table": ("overall", "Project summary", "table: project, owner, progress, status, key achievement (written by the AI)"),
    "team_pie": ("overall", "Team effort", "pie chart of the effort per person and project"),
    "effort_project_table": ("overall", "Effort by project", "table of hours per project"),
    "effort_activity_pie": ("overall", "Effort by activity", "pie chart of the effort per activity type"),
    "risks_all_table": ("overall", "All risks & blockers", "table of blocked and overdue tasks across projects"),
    "upcoming_all_table": ("overall", "All upcoming work", "table of tasks due in the next 14 days across projects"),
}
VISUAL = {  # what the preview shows as a hint next to a section
    "header_table": "table", "kpi_row": "table", "status_pie": "chart", "workflow": "flow", "activities_table": "table", "deliverables_table": "table",
    "work_pie": "chart", "risks_table": "table", "upcoming_table": "table", "totals_row": "table", "health_pie": "chart", "projects_table": "table",
    "team_pie": "chart", "effort_project_table": "table", "effort_activity_pie": "chart", "risks_all_table": "table", "upcoming_all_table": "table",
}


def _table(head: list[str], rows: list[list[Any]], empty: str) -> list[str]:
    if not rows:
        return [f"_{empty}_", ""]
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head), *["| " + " | ".join(esc(c) for c in r) + " |" for r in rows], ""]


def _status(p: dict[str, Any]) -> str:
    return STATUS_LABEL[p["status"]]


# ----------------------------------------------------------------------------------------------- per project
def header_table(p, f, n):
    rows = ["| | |", "|---|---|", f"| **Reporting Period** | {nice_period(f['period'])} |", f"| **Project** | {esc(p['name'])} |"]
    if p.get("owners") is not None:
        rows.append(f"| **Owner** | {esc(', '.join(p['owners']) or '—')} |")
    return [*rows, f"| **Status** | {_status(p)} |", ""]


def kpi_row(p, f, n):
    return ["| 🎯 Planned Tasks | ✅ Completed | 🚧 In Progress | 📅 Pending | 📊 Progress |", "|:---:|:---:|:---:|:---:|:---:|",
            f"| **{p['planned']}** | **{p['completed']}** | **{p['in_progress']}** | **{p['pending']}** | **{p['progress']}%** |", ""]


def status_pie(p, f, n):
    return _pie("Status distribution", [("Completed", p["completed"]), ("In Progress", p["in_progress"]), ("Pending", p["pending"])]) or ["_No tasks._", ""]


def workflow(p, f, n):
    text = str(n.get(f"workflow::{p['name']}") or "")
    stages = [s.strip() for s in text.replace("→", "->").split("->") if s.strip()] or fallback_workflow(p)
    return _flow(stages[:7])


def activities_table(p, f, n):
    return _table(["Activity", "Status"], [[a["title"], ACTIVITY_STATUS.get(a["status"], "🚧 In Progress")] for a in p["activities"]], "No tasks in this period.")


def deliverables_table(p, f, n):
    return _table(["#", "Deliverable", "Status"], [[i, d, "✅"] for i, d in enumerate(p["deliverables"], 1)], "No deliverables were completed in this period.")


def work_pie(p, f, n):
    return _pie("Work distribution", [(d["label"], d["pct"]) for d in p["work_distribution"]]) or ["_No effort was logged._", ""]


def _risk_rows(p: dict[str, Any], with_project: bool = False) -> list[list[Any]]:
    pre = [p["name"]] if with_project else []
    return [*[[*pre, t, "🔴 Blocked"] for t in p.get("blocked", [])], *[[*pre, o["title"], f"⏰ Overdue by {o['days_late']} day(s)"] for o in p.get("overdue", [])]]


def risks_table(p, f, n):
    return _table(["Item", "Issue"], _risk_rows(p), "No blocked or overdue work.")


def upcoming_table(p, f, n):
    return _table(["Task", "Due"], [[u["title"], u["due_date"]] for u in p.get("upcoming", [])], "Nothing is due in the next 14 days.")


# ----------------------------------------------------------------------------------------------- overall
def totals_row(f):
    t = f["totals"]
    pct = round(t["completed"] / t["planned"] * 100) if t["planned"] else 0
    return ["| 📁 Projects | 🎯 Planned | ✅ Completed | 🚧 In Progress | 📅 Pending | 📊 Progress | ⏱ Hours |", "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
            f"| **{t['projects']}** | **{t['planned']}** | **{t['completed']}** | **{t['in_progress']}** | **{t['pending']}** | **{pct}%** | **{t['hours']:g}** |", ""]


def health_pie(f):
    return _pie("Project progress", [(f"{p['name']} ({p['progress']}%)", max(p["progress"], 1)) for p in f["projects"]]) or ["_No progress yet._", ""]


def projects_table(f, n):
    internal = any(p.get("owners") is not None for p in f["projects"])
    head = ["Project", *(["Owner"] if internal else []), "Progress", "Status", "Key achievement"]
    rows = [[p["name"], *([", ".join(p.get("owners") or []) or "—"] if internal else []), f"{p['progress']}%", _status(p).split()[0],
             str(n.get(f"key::{p['name']}") or "") or _achievement(p)] for p in f["projects"]]
    return _table(head, rows, "No projects.")


def _achievement(p: dict[str, Any]) -> str:
    if p["deliverables"]:
        return f"{p['completed']} of {p['planned']} tasks completed; latest: {p['deliverables'][-1]}"
    return f"{p['in_progress']} task{'s' if p['in_progress'] != 1 else ''} in progress"


def team_pie(f):
    return _pie("Effort per person and project", [(d["label"], d["pct"]) for d in f.get("team_distribution", [])]) or ["_No effort was logged._", ""]


def effort_project_table(f):
    total = sum(p["hours"] for p in f["projects"]) or 1
    return _table(["Project", "Hours", "Share"], [[p["name"], f"{p['hours']:g}", f"{round(p['hours'] / total * 100)}%"] for p in f["projects"] if p["hours"]], "No effort was logged.")


def effort_activity_pie(f):
    return _pie("Effort by activity", [(d["label"], d["pct"]) for d in f.get("hours_by_activity", [])]) or ["_No effort was logged._", ""]


def risks_all_table(f):
    return _table(["Project", "Item", "Issue"], [r for p in f["projects"] for r in _risk_rows(p, True)], "No blocked or overdue work across the projects.")


def upcoming_all_table(f):
    rows = sorted(([p["name"], u["title"], u["due_date"]] for p in f["projects"] for u in p.get("upcoming", [])), key=lambda r: r[2])
    return _table(["Project", "Task", "Due"], rows, "Nothing is due in the next 14 days.")


PER_PROJECT = {"header_table": header_table, "kpi_row": kpi_row, "status_pie": status_pie, "workflow": workflow, "activities_table": activities_table,
               "deliverables_table": deliverables_table, "work_pie": work_pie, "risks_table": risks_table, "upcoming_table": upcoming_table}
OVERALL = {"totals_row": lambda f, n: totals_row(f), "health_pie": lambda f, n: health_pie(f), "projects_table": projects_table,
           "team_pie": lambda f, n: team_pie(f), "effort_project_table": lambda f, n: effort_project_table(f),
           "effort_activity_pie": lambda f, n: effort_activity_pie(f), "risks_all_table": lambda f, n: risks_all_table(f),
           "upcoming_all_table": lambda f, n: upcoming_all_table(f)}
