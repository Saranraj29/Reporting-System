import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select, text

from ..config import get_settings
from ..deps import Ctx, Page, get_ctx, paged, pagination, require, require_any
from ..errors import bad_request, conflict, not_found
from ..models import Permission, Role, RolePermission, Team, TeamMember, User, UserRole
from ..perms import PERMISSIONS
from ..security import hash_password, make_email_token
from ..services import mail
from ..services.access import clear_permission_cache, owned_project_ids

router = APIRouter(tags=["people"])


# --------------------------------------------------------------------------- /me
@router.get("/me")
def me(ctx: Ctx = Depends(get_ctx)):
    roles = ctx.db.execute(
        select(Role.id, Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == ctx.me.id)
    ).all()
    return {
        "id": str(ctx.me.id),
        "email": ctx.me.email,
        "name": ctx.me.name,
        "company": {"id": str(ctx.company.id), "name": ctx.company.name, "timezone": ctx.company.timezone},
        "roles": [{"id": str(r.id), "name": r.name} for r in roles],
        "permissions": sorted(ctx.perms),
        "owns_projects": bool(owned_project_ids(ctx.db, ctx.me.id)),  # project owners can request AI reports for their projects
    }


# --------------------------------------------------------------------------- users
def _user_out(u: User, roles: list[dict], full: bool) -> dict:
    out = {"id": str(u.id), "name": u.name, "email": u.email, "is_active": u.is_active, "roles": roles}
    if full:
        out["email_verified"] = u.email_verified_at is not None
        out["has_google"] = bool(u.google_id)
    return out


def _roles_by_user(ctx: Ctx, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    rows = ctx.db.execute(
        select(UserRole.user_id, Role.id, Role.name)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(user_ids))
    ).all()
    out: dict[uuid.UUID, list[dict]] = {}
    for uid, rid, name in rows:
        out.setdefault(uid, []).append({"id": str(rid), "name": name})
    return out


@router.get("/users")
def list_users(
    q: str | None = None, active: bool | None = None,
    ctx: Ctx = Depends(require_any("user.manage", "task.view", "status.view", "dashboard.view")),
    page: Page = Depends(pagination),
):
    admin = ctx.has("user.manage")
    stmt = select(User).order_by(User.name)
    if not admin:  # everyone else only sees people inside their own scope (for assignee pickers etc.)
        ids = ctx.visible("task.view") if ctx.scope_of("task.view") else ctx.visible("status.view")
        if ids is not None:
            stmt = stmt.where(User.id.in_(ids))
        stmt = stmt.where(User.is_active.is_(True))
    if q:
        stmt = stmt.where(User.name.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))
    if active is not None:
        stmt = stmt.where(User.is_active == active)
    result = paged(ctx.db, stmt, page, lambda u: u)
    roles = _roles_by_user(ctx, [u.id for u in result["items"]])
    result["items"] = [_user_out(u, roles.get(u.id, []), admin) for u in result["items"]]
    return result


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role_ids: list[uuid.UUID] = []


def _validate_roles(ctx: Ctx, role_ids: list[uuid.UUID]) -> None:
    if role_ids:
        found = ctx.db.execute(select(func.count()).select_from(Role).where(Role.id.in_(role_ids))).scalar_one()
        if found != len(set(role_ids)):
            raise bad_request("invalid_role", "One or more roles do not exist")


def _email_taken(ctx: Ctx, email: str) -> bool:
    return ctx.db.execute(text("SELECT 1 FROM auth_user_by_email(:e)"), {"e": email}).first() is not None


@router.post("/users", status_code=201)
def create_user(body: UserCreate, ctx: Ctx = Depends(require("user.manage"))):
    if _email_taken(ctx, body.email):
        raise conflict("email_taken", "An account with this email already exists")
    _validate_roles(ctx, body.role_ids)
    role_ids = body.role_ids or [ctx.db.execute(select(Role.id).where(Role.name == "Team Member")).scalar_one()]
    user = User(
        company_id=ctx.company_id, email=body.email.lower(), name=body.name,
        password_hash=hash_password(body.password), email_verified_at=datetime.now(UTC),
    )
    ctx.db.add(user)
    ctx.db.flush()
    ctx.db.add_all(UserRole(company_id=ctx.company_id, user_id=user.id, role_id=r) for r in set(role_ids))
    ctx.db.commit()
    clear_permission_cache()
    return _user_out(user, list(_roles_by_user(ctx, [user.id]).get(user.id, [])), True)


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
    role_ids: list[uuid.UUID] | None = None


@router.patch("/users/{user_id}")
def patch_user(user_id: uuid.UUID, body: UserPatch, ctx: Ctx = Depends(require("user.manage"))):
    user = ctx.db.get(User, user_id)
    if not user:
        raise not_found("User")
    if body.name is not None:
        user.name = body.name
    if body.is_active is not None:
        if user.id == ctx.me.id and not body.is_active:
            raise bad_request("cannot_deactivate_self", "You cannot deactivate your own account")
        user.is_active = body.is_active
        if not body.is_active:
            user.refresh_version += 1
    if body.role_ids is not None:
        _validate_roles(ctx, body.role_ids)
        if user.id == ctx.me.id and not _keeps_user_manage(ctx, body.role_ids):
            raise bad_request("cannot_lock_out", "You cannot remove your own user-management access")
        ctx.db.execute(delete(UserRole).where(UserRole.user_id == user.id))
        ctx.db.add_all(UserRole(company_id=ctx.company_id, user_id=user.id, role_id=r) for r in set(body.role_ids))
    ctx.db.commit()
    clear_permission_cache()
    return _user_out(user, list(_roles_by_user(ctx, [user.id]).get(user.id, [])), True)


def _keeps_user_manage(ctx: Ctx, role_ids: list[uuid.UUID]) -> bool:
    return bool(
        ctx.db.execute(
            select(func.count()).select_from(RolePermission).where(
                RolePermission.role_id.in_(role_ids), RolePermission.permission_key == "user.manage"
            )
        ).scalar_one()
    )


class InviteIn(BaseModel):
    email: EmailStr
    role_id: uuid.UUID | None = None


@router.post("/users/invite", status_code=201)
def invite_user(body: InviteIn, ctx: Ctx = Depends(require("user.manage"))):
    if _email_taken(ctx, body.email):
        raise conflict("email_taken", "An account with this email already exists")
    role_id = body.role_id or ctx.db.execute(select(Role.id).where(Role.name == "Team Member")).scalar_one()
    _validate_roles(ctx, [role_id])
    token = make_email_token("invite", 24 * 7, email=body.email.lower(), company_id=str(ctx.company_id), role_id=str(role_id))
    link = f"{get_settings().public_web_url}/register?invite={token}"
    mail.send_email(
        body.email, f"{ctx.company.name} invited you", f"{ctx.me.name} invited you to join {ctx.company.name}:\n{link}\n"
    )
    out = {"message": "Invite sent", "email": body.email.lower()}
    if get_settings().app_env != "prod":
        out["dev_invite_link"] = link
    return out


# --------------------------------------------------------------------------- roles & permissions
@router.get("/permissions")
def list_permissions(ctx: Ctx = Depends(require_any("role.manage", "user.manage"))):
    rows = ctx.db.execute(select(Permission).order_by(Permission.key)).scalars().all()
    return {"items": [{"key": p.key, "description": p.description} for p in rows]}


def _role_out(ctx: Ctx, roles: list[Role]) -> list[dict]:
    ids = [r.id for r in roles]
    keys: dict[uuid.UUID, list[str]] = {}
    for rid, key in ctx.db.execute(
        select(RolePermission.role_id, RolePermission.permission_key).where(RolePermission.role_id.in_(ids))
    ):
        keys.setdefault(rid, []).append(key)
    counts = dict(
        ctx.db.execute(select(UserRole.role_id, func.count()).where(UserRole.role_id.in_(ids)).group_by(UserRole.role_id)).all()
    )
    return [
        {
            "id": str(r.id), "name": r.name, "description": r.description,
            "permissions": sorted(keys.get(r.id, [])), "user_count": counts.get(r.id, 0),
        }
        for r in roles
    ]


@router.get("/roles")
def list_roles(ctx: Ctx = Depends(require_any("role.manage", "user.manage"))):
    roles = ctx.db.execute(select(Role).order_by(Role.name)).scalars().all()
    return {"items": _role_out(ctx, roles)}


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    permissions: list[str] = []


def _check_keys(keys: list[str]) -> None:
    bad = sorted(set(keys) - set(PERMISSIONS))
    if bad:
        raise bad_request("invalid_permission", f"Unknown permission keys: {', '.join(bad)}")


@router.post("/roles", status_code=201)
def create_role(body: RoleIn, ctx: Ctx = Depends(require("role.manage"))):
    _check_keys(body.permissions)
    if ctx.db.execute(select(Role.id).where(func.lower(Role.name) == body.name.lower())).first():
        raise conflict("role_exists", "A role with this name already exists")
    role = Role(company_id=ctx.company_id, name=body.name, description=body.description)
    ctx.db.add(role)
    ctx.db.flush()
    ctx.db.add_all(RolePermission(company_id=ctx.company_id, role_id=role.id, permission_key=k) for k in set(body.permissions))
    ctx.db.commit()
    return _role_out(ctx, [role])[0]


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    permissions: list[str] | None = None


@router.patch("/roles/{role_id}")
def patch_role(role_id: uuid.UUID, body: RolePatch, ctx: Ctx = Depends(require("role.manage"))):
    role = ctx.db.get(Role, role_id)
    if not role:
        raise not_found("Role")
    if body.name is not None:
        clash = ctx.db.execute(select(Role.id).where(func.lower(Role.name) == body.name.lower(), Role.id != role.id)).first()
        if clash:
            raise conflict("role_exists", "A role with this name already exists")
        role.name = body.name
    if body.description is not None:
        role.description = body.description
    if body.permissions is not None:
        _check_keys(body.permissions)
        mine = ctx.db.execute(select(UserRole.role_id).where(UserRole.user_id == ctx.me.id)).scalars().all()
        if role.id in mine and "role.manage" not in body.permissions:
            raise bad_request("cannot_lock_out", "You cannot remove role management from a role you hold")
        ctx.db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        ctx.db.add_all(RolePermission(company_id=ctx.company_id, role_id=role.id, permission_key=k) for k in set(body.permissions))
    ctx.db.commit()
    clear_permission_cache()
    return _role_out(ctx, [role])[0]


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: uuid.UUID, ctx: Ctx = Depends(require("role.manage"))):
    role = ctx.db.get(Role, role_id)
    if not role:
        raise not_found("Role")
    if ctx.db.execute(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)).scalar_one():
        raise conflict("role_in_use", "Remove this role from its users before deleting it")
    ctx.db.delete(role)
    ctx.db.commit()
    clear_permission_cache()


# --------------------------------------------------------------------------- teams
class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    lead_user_id: uuid.UUID | None = None


class TeamPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    lead_user_id: uuid.UUID | None = None


class MembersIn(BaseModel):
    user_ids: list[uuid.UUID]


def _team_out(ctx: Ctx, teams: list[Team]) -> list[dict]:
    members: dict[uuid.UUID, list[str]] = {}
    for tid, uid in ctx.db.execute(select(TeamMember.team_id, TeamMember.user_id).where(TeamMember.team_id.in_([t.id for t in teams]))):
        members.setdefault(tid, []).append(str(uid))
    return [
        {"id": str(t.id), "name": t.name, "lead_user_id": str(t.lead_user_id) if t.lead_user_id else None,
         "member_ids": members.get(t.id, [])}
        for t in teams
    ]


def _check_users(ctx: Ctx, ids: list[uuid.UUID]) -> None:
    if ids and ctx.db.execute(select(func.count()).select_from(User).where(User.id.in_(ids))).scalar_one() != len(set(ids)):
        raise bad_request("invalid_user", "One or more users do not exist")


@router.get("/teams")
def list_teams(ctx: Ctx = Depends(get_ctx)):
    teams = ctx.db.execute(select(Team).order_by(Team.name)).scalars().all()
    return {"items": _team_out(ctx, list(teams))}


@router.post("/teams", status_code=201)
def create_team(body: TeamIn, ctx: Ctx = Depends(require("project.manage"))):
    if body.lead_user_id:
        _check_users(ctx, [body.lead_user_id])
    if ctx.db.execute(select(Team.id).where(func.lower(Team.name) == body.name.lower())).first():
        raise conflict("team_exists", "A team with this name already exists")
    team = Team(company_id=ctx.company_id, name=body.name, lead_user_id=body.lead_user_id)
    ctx.db.add(team)
    ctx.db.commit()
    return _team_out(ctx, [team])[0]


@router.patch("/teams/{team_id}")
def patch_team(team_id: uuid.UUID, body: TeamPatch, ctx: Ctx = Depends(require("project.manage"))):
    team = ctx.db.get(Team, team_id)
    if not team:
        raise not_found("Team")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        team.name = data["name"]
    if "lead_user_id" in data:
        if data["lead_user_id"]:
            _check_users(ctx, [data["lead_user_id"]])
        team.lead_user_id = data["lead_user_id"]
    ctx.db.commit()
    return _team_out(ctx, [team])[0]


@router.put("/teams/{team_id}/members")
def set_team_members(team_id: uuid.UUID, body: MembersIn, ctx: Ctx = Depends(require("project.manage"))):
    team = ctx.db.get(Team, team_id)
    if not team:
        raise not_found("Team")
    _check_users(ctx, body.user_ids)
    ctx.db.execute(delete(TeamMember).where(TeamMember.team_id == team.id))
    ctx.db.add_all(TeamMember(company_id=ctx.company_id, team_id=team.id, user_id=u) for u in set(body.user_ids))
    ctx.db.commit()
    return _team_out(ctx, [team])[0]


