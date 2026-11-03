"""Permission loading and scope resolution shared by the API guard and the worker."""

import time
import uuid

from sqlalchemy import select, union
from sqlalchemy.orm import Session

from ..models import RolePermission, Team, TeamMember, UserRole
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
