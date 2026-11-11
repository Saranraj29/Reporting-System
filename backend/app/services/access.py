"""Permission loading and scope resolution shared by the API guard and the worker."""

import time
import uuid

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from ..models import Project, ProjectMember, RolePermission, Task, TaskAssignee, Team, TeamMember, UserRole
from ..perms import best_scope

_CACHE: dict[uuid.UUID, tuple[float, frozenset[str]]] = {}
_TTL = 300.0  # roles are loaded once per user and cached for 5 minutes


def clear_permission_cache() -> None:
    _CACHE.clear()


def load_permissions(db: Session, user_id: uuid.UUID, use_cache: bool = True) -> frozenset[str]:
    now = time.monotonic()
    hit = _CACHE.get(user_id)
    if use_cache and hit and hit[0] > now:
        return hit[1]
    rows = db.execute(
        select(RolePermission.permission_key)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    ).scalars()
    perms = frozenset(rows)  # a user with several roles gets the union of their keys
    _CACHE[user_id] = (now + _TTL, perms)
    return perms


def team_user_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Users in teams I lead or belong to (always includes me)."""
    team_ids = union(
        select(Team.id).where(Team.lead_user_id == user_id),
        select(TeamMember.team_id).where(TeamMember.user_id == user_id),
    ).subquery()
    members = set(db.execute(select(TeamMember.user_id).where(TeamMember.team_id.in_(select(team_ids)))).scalars())
    leads = set(db.execute(select(Team.lead_user_id).where(Team.id.in_(select(team_ids)))).scalars())
    return {user_id} | members | {x for x in leads if x}


def visible_users(db: Session, user_id: uuid.UUID, perms: frozenset[str], base: str):
    """Returns (scope, ids) where ids is None for 'all', else the set of user ids the scope covers."""
    scope = best_scope(perms, base)
    if scope is None:
        return None, set()
    if scope == "all":
        return scope, None
    if scope == "own":
        return scope, {user_id}
    return scope, team_user_ids(db, user_id)


def owned_project_ids(db: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Projects the user owns. Owners see every task, comment and time entry in those projects,
    regardless of who created or is assigned to them (view access; editing still follows task.edit.*)."""
    return list(db.execute(select(ProjectMember.project_id).where(ProjectMember.user_id == user_id, ProjectMember.is_owner.is_(True))).scalars())


def member_project_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Projects the user works on: member or owner."""
    return set(db.execute(select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)).scalars())


def my_team_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Teams I lead or belong to."""
    return set(db.execute(union(select(Team.id).where(Team.lead_user_id == user_id), select(TeamMember.team_id).where(TeamMember.user_id == user_id))).scalars())


def project_people(db: Session, project_id: uuid.UUID) -> set[uuid.UUID]:
    """Members and owners of a project."""
    return set(db.execute(select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)).scalars())


def task_project_ids(db: Session, user_id: uuid.UUID, scope: str | None) -> set[uuid.UUID] | None:
    """Projects the user may add tasks to (None = every project). Everyone: the projects they are a member or owner of; a team lead / team
    scope also the projects of the teams they lead or belong to; the 'all' scope every project."""
    if scope == "all":
        return None
    ids = member_project_ids(db, user_id)
    if scope == "team":
        teams = my_team_ids(db, user_id)
        if teams:
            ids |= set(db.execute(select(Project.id).where(Project.team_id.in_(teams))).scalars())
    return ids


def visible_project_ids(db: Session, user_id: uuid.UUID, perms: frozenset[str]) -> set[uuid.UUID] | None:
    """The projects a person has any business seeing in a list or a filter (None = every project): the ones they work on, the ones where
    someone in their task scope has a task, and for a team scope the projects of their teams. Managers, admins and project managers see all."""
    if "project.manage" in perms or any(best_scope(perms, base) == "all" for base in ("task.view", "dashboard.view")):
        return None
    ids = member_project_ids(db, user_id)
    scope, people = visible_users(db, user_id, perms, "task.view")
    if people:
        ids |= set(db.execute(select(Task.project_id).join(TaskAssignee, TaskAssignee.task_id == Task.id).where(TaskAssignee.user_id.in_(people))).scalars())
    if scope == "team":
        teams = my_team_ids(db, user_id)
        if teams:
            ids |= set(db.execute(select(Project.id).where(Project.team_id.in_(teams))).scalars())
    return ids


def visible_team_ids(db: Session, user_id: uuid.UUID, perms: frozenset[str]) -> set[uuid.UUID] | None:
    """The teams a person sees in a list or a filter (None = all): their own teams and the teams of the projects they can see."""
    project_ids = visible_project_ids(db, user_id, perms)
    if project_ids is None:
        return None
    teams = my_team_ids(db, user_id)
    if project_ids:
        teams |= {t for t in db.execute(select(Project.team_id).where(Project.id.in_(project_ids), Project.team_id.is_not(None))).scalars()}
    return teams
