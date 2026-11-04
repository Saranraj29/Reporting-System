"""Permission keys (area.action.scope) and the roles seeded for every new company."""

SCOPES = ("own", "team", "all")  # ascending reach

PERMISSIONS: dict[str, str] = {
    "task.view.own": "See tasks assigned to me",
    "task.view.team": "See tasks of my team",
    "task.view.all": "See all tasks",
    "task.edit.own": "Create/edit tasks assigned to me and log my time",
    "task.edit.team": "Create/edit tasks for my team",
    "task.edit.all": "Create/edit any task",
    "status.view.own": "See my daily status",
    "status.view.team": "See my team's daily status",
    "status.view.all": "See everyone's daily status",
    "dashboard.view.own": "Dashboard of my own work",
    "dashboard.view.team": "Dashboard for my team",
    "dashboard.view.all": "Company-wide dashboard",
    "report.weekly.view.team": "Weekly report (team)",
    "report.weekly.view.all": "Weekly report (company)",
    "report.monthly.view.team": "Monthly report (team)",
    "report.monthly.view.all": "Monthly report (company)",
    "report.performance.view.team": "Performance report (team)",
    "report.performance.view.all": "Performance report (company)",
    "report.visibility.view.team": "Project visibility report (team)",
    "report.visibility.view.all": "Project visibility report (company)",
    "report.template.manage": "Manage report templates",
    "report.ai.draft": "Generate AI-drafted client reports",
    "report.approve": "Approve client reports",
    "report.share.client": "Share approved reports with clients",
    "user.manage": "Manage users",
    "role.manage": "Manage roles and permissions",
    "project.manage": "Manage projects, teams and clients",
    "settings.manage": "Manage company settings, Slack link, task fields",
}

_ADMIN = ["user.manage", "role.manage", "project.manage", "settings.manage"]
_CLIENT = ["report.template.manage", "report.ai.draft", "report.approve", "report.share.client"]
_REPORTS_ALL = [f"report.{r}.view.all" for r in ("weekly", "monthly", "performance", "visibility")]
_REPORTS_TEAM = [f"report.{r}.view.team" for r in ("weekly", "monthly", "performance", "visibility")]

DEFAULT_ROLE = "Team Member"

SEEDED_ROLES: dict[str, tuple[str, list[str]]] = {
    "Team Member": (
        "Own tasks, hours and status",
        ["task.view.own", "task.edit.own", "status.view.own", "dashboard.view.own"],
    ),
    "Team Lead": (
        "Team tasks, hours, weekly/monthly/performance reports for their team",
        ["task.view.team", "task.edit.team", "status.view.team", "dashboard.view.team", *_REPORTS_TEAM],
    ),
    "Manager": (
        "All projects and teams, all reports, client reports",
        [
            "task.view.all", "task.edit.all", "status.view.all", "dashboard.view.all", *_REPORTS_ALL,
            *_CLIENT, "project.manage",
        ],
    ),
    "CEO / CTO": ("Everything, all reports", list(PERMISSIONS)),
    "Company Admin": (
        "Users, roles, projects, settings, Slack link (no performance reports unless also given that key)",
        [
            *_ADMIN, "task.view.all", "task.edit.all", "status.view.all", "dashboard.view.all",
            "report.weekly.view.all", "report.monthly.view.all", "report.visibility.view.all", "report.template.manage",
        ],
    ),
}


def best_scope(perms: set[str] | frozenset[str], base: str) -> str | None:
    """Highest scope held for a `area.action` base key, or None."""
    for scope in reversed(SCOPES):
        if f"{base}.{scope}" in perms:
            return scope
    return None


def is_scoped_base(base: str) -> bool:
    return any(f"{base}.{s}" in PERMISSIONS for s in SCOPES)
