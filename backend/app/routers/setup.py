"""Projects, clients (+contacts), company settings and task-field definitions."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from sqlalchemy import delete, func, select, text

from ..deps import Ctx, Page, get_ctx, paged, pagination, require, require_any
from ..errors import bad_request, conflict, not_found
from ..models import (
    Client,
    ClientContact,
    NotificationLog,
    Project,
    ProjectMember,
    TaskFieldDefinition,
    Team,
    User,
)
from ..security import decrypt, encrypt
from ..services.timeutil import valid_timezone
from .auth import PUBLIC_DOMAINS

router = APIRouter(tags=["setup"])


# --------------------------------------------------------------------------- projects
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    client_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    status: str = Field(default="active", pattern="^(active|on_hold|completed|archived)$")
    start_date: date | None = None
    end_date: date | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    client_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    status: str | None = Field(default=None, pattern="^(active|on_hold|completed|archived)$")
    start_date: date | None = None
    end_date: date | None = None


def _project_out(p: Project, client_name: str | None = None, members: list[str] | None = None, owners: list[str] | None = None,
                 team_name: str | None = None) -> dict:
    return {
        "id": str(p.id), "name": p.name, "client_id": str(p.client_id) if p.client_id else None,
        "client_name": client_name, "status": p.status, "team_id": str(p.team_id) if p.team_id else None, "team_name": team_name,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "member_ids": members or [], "owner_ids": owners or [],
    }


def _members(ctx: Ctx, ids: list[uuid.UUID], owners_only: bool = False) -> dict[uuid.UUID, list[str]]:
    out: dict[uuid.UUID, list[str]] = {}
    stmt = select(ProjectMember.project_id, ProjectMember.user_id).where(ProjectMember.project_id.in_(ids))
    if owners_only:
        stmt = stmt.where(ProjectMember.is_owner.is_(True))
    for pid, uid in ctx.db.execute(stmt):
        out.setdefault(pid, []).append(str(uid))
    return out


def _check_client(ctx: Ctx, client_id: uuid.UUID | None) -> None:
    if client_id and not ctx.db.get(Client, client_id):
        raise bad_request("invalid_client", "Client does not exist")


def _check_team(ctx: Ctx, team_id: uuid.UUID | None) -> None:
    if team_id and not ctx.db.get(Team, team_id):
        raise bad_request("invalid_team", "Team does not exist")


def _team_name(ctx: Ctx, team_id: uuid.UUID | None) -> str | None:
    return ctx.db.execute(select(Team.name).where(Team.id == team_id)).scalar_one_or_none() if team_id else None


@router.get("/projects")
def list_projects(
    status: str | None = None, client_id: uuid.UUID | None = None, team: uuid.UUID | None = None, q: str | None = None,
    ctx: Ctx = Depends(get_ctx), page: Page = Depends(pagination),
):
    stmt = (select(Project, Client.name, Team.name).outerjoin(Client, Client.id == Project.client_id)
            .outerjoin(Team, Team.id == Project.team_id).order_by(Project.name))
    if status:
        stmt = stmt.where(Project.status == status)
    if client_id:
        stmt = stmt.where(Project.client_id == client_id)
    if team:
        stmt = stmt.where(Project.team_id == team)
    if q:
        stmt = stmt.where(Project.name.ilike(f"%{q}%") | Client.name.ilike(f"%{q}%") | Team.name.ilike(f"%{q}%"))
    total = ctx.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = ctx.db.execute(stmt.limit(page.limit).offset(page.offset)).all()
    ids = [p.id for p, _, _ in rows]
    members, owners = _members(ctx, ids), _members(ctx, ids, owners_only=True)
    return {
        "items": [_project_out(p, cn, members.get(p.id), owners.get(p.id), tn) for p, cn, tn in rows],
        "total": total, "page": page.page, "limit": page.limit,
    }


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, ctx: Ctx = Depends(require("project.manage"))):
    _check_client(ctx, body.client_id)
    _check_team(ctx, body.team_id)
    if ctx.db.execute(select(Project.id).where(func.lower(Project.name) == body.name.lower())).first():
        raise conflict("project_exists", "A project with this name already exists")
    p = Project(company_id=ctx.company_id, **body.model_dump())
    ctx.db.add(p)
    ctx.db.commit()
    return _project_out(p, team_name=_team_name(ctx, p.team_id))


@router.patch("/projects/{project_id}")
def patch_project(project_id: uuid.UUID, body: ProjectPatch, ctx: Ctx = Depends(require("project.manage"))):
    p = ctx.db.get(Project, project_id)
    if not p:
        raise not_found("Project")
    data = body.model_dump(exclude_unset=True)
    if data.get("client_id"):
        _check_client(ctx, data["client_id"])
    if data.get("team_id"):
        _check_team(ctx, data["team_id"])
    for k, v in data.items():
        if k in ("name", "status") and v is None:
            continue
        setattr(p, k, v)
    ctx.db.commit()
    return _project_out(p, members=_members(ctx, [p.id]).get(p.id), owners=_members(ctx, [p.id], owners_only=True).get(p.id), team_name=_team_name(ctx, p.team_id))


class ProjectMembersIn(BaseModel):
    user_ids: list[uuid.UUID]
    owner_ids: list[uuid.UUID] = []  # project owners; they are added as members automatically


@router.get("/projects/{project_id}/members")
def get_project_members(project_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    if not ctx.db.get(Project, project_id):
        raise not_found("Project")
    return {
        "user_ids": _members(ctx, [project_id]).get(project_id, []),
        "owner_ids": _members(ctx, [project_id], owners_only=True).get(project_id, []),
    }


@router.put("/projects/{project_id}/members")
def set_project_members(project_id: uuid.UUID, body: ProjectMembersIn, ctx: Ctx = Depends(require("project.manage"))):
    """Replaces the member list. Owners get view access to every task in this project (whoever created or is assigned)."""
    if not ctx.db.get(Project, project_id):
        raise not_found("Project")
    owners = set(body.owner_ids)
    ids = set(body.user_ids) | owners
    if ids and ctx.db.execute(select(func.count()).select_from(User).where(User.id.in_(ids))).scalar_one() != len(ids):
        raise bad_request("invalid_user", "One or more users do not exist")
    ctx.db.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id))
    ctx.db.add_all(ProjectMember(company_id=ctx.company_id, project_id=project_id, user_id=u, is_owner=u in owners) for u in ids)
    ctx.db.commit()
    return {"user_ids": [str(u) for u in ids], "owner_ids": [str(u) for u in owners]}


# --------------------------------------------------------------------------- clients
class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    contact_name: str | None = None
    contact_email: EmailStr | None = None


class ClientPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    contact_name: str | None = None
    contact_email: EmailStr | None = None


def _client_out(c: Client) -> dict:
    return {"id": str(c.id), "name": c.name, "contact_name": c.contact_name, "contact_email": c.contact_email}


CLIENT_READ = require_any("project.manage", "report.template.manage", "report.share.client", "report.ai.draft")


@router.get("/clients")
def list_clients(q: str | None = None, ctx: Ctx = Depends(CLIENT_READ), page: Page = Depends(pagination)):
    stmt = select(Client).order_by(Client.name)
    if q:
        stmt = stmt.where(Client.name.ilike(f"%{q}%") | Client.contact_name.ilike(f"%{q}%") | Client.contact_email.ilike(f"%{q}%"))
    return paged(ctx.db, stmt, page, _client_out)


@router.post("/clients", status_code=201)
def create_client(body: ClientIn, ctx: Ctx = Depends(require("project.manage"))):
    if ctx.db.execute(select(Client.id).where(func.lower(Client.name) == body.name.lower())).first():
        raise conflict("client_exists", "A client with this name already exists")
    c = Client(company_id=ctx.company_id, **body.model_dump())
    ctx.db.add(c)
    ctx.db.flush()
    if c.contact_email:  # the primary contact is also a recipient candidate for shared reports
        ctx.db.add(ClientContact(company_id=ctx.company_id, client_id=c.id, name=c.contact_name or c.contact_email, email=c.contact_email.lower()))
    ctx.db.commit()
    return _client_out(c)


@router.patch("/clients/{client_id}")
def patch_client(client_id: uuid.UUID, body: ClientPatch, ctx: Ctx = Depends(require("project.manage"))):
    c = ctx.db.get(Client, client_id)
    if not c:
        raise not_found("Client")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "name" and not v:
            continue
        setattr(c, k, v)
    ctx.db.commit()
    return _client_out(c)


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr


def _contact_out(c: ClientContact) -> dict:
    return {"id": str(c.id), "name": c.name, "email": c.email}


@router.get("/clients/{client_id}/contacts")
def list_contacts(client_id: uuid.UUID, ctx: Ctx = Depends(CLIENT_READ)):
    if not ctx.db.get(Client, client_id):
        raise not_found("Client")
    rows = ctx.db.execute(select(ClientContact).where(ClientContact.client_id == client_id).order_by(ClientContact.name)).scalars()
    return {"items": [_contact_out(c) for c in rows]}


@router.post("/clients/{client_id}/contacts", status_code=201)
def add_contact(client_id: uuid.UUID, body: ContactIn, ctx: Ctx = Depends(require("project.manage"))):
    if not ctx.db.get(Client, client_id):
        raise not_found("Client")
    email = body.email.lower()
    if ctx.db.execute(select(ClientContact.id).where(ClientContact.client_id == client_id, ClientContact.email == email)).first():
        raise conflict("contact_exists", "This contact already exists")
    c = ClientContact(company_id=ctx.company_id, client_id=client_id, name=body.name, email=email)
    ctx.db.add(c)
    ctx.db.commit()
    return _contact_out(c)


@router.delete("/clients/{client_id}/contacts/{contact_id}", status_code=204)
def delete_contact(client_id: uuid.UUID, contact_id: uuid.UUID, ctx: Ctx = Depends(require("project.manage"))):
    c = ctx.db.get(ClientContact, contact_id)
    if not c or c.client_id != client_id:
        raise not_found("Contact")
    ctx.db.delete(c)
    ctx.db.commit()


# --------------------------------------------------------------------------- settings
class SettingsPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    slack_webhook_url: HttpUrl | None = None
    clear_slack: bool = False
    report_email_day: int | None = Field(default=None, ge=0, le=6)
    report_email_enabled: bool | None = None
    timezone: str | None = None
    email_domain: str | None = None
    ai_enabled: bool | None = None


def _settings_out(ctx: Ctx) -> dict:
    c = ctx.company
    admin = ctx.has("settings.manage")
    out = {
        "name": c.name, "timezone": c.timezone, "email_domain": c.email_domain,
        "report_email_enabled": c.report_email_day is not None, "report_email_day": c.report_email_day,
        "slack_configured": bool(c.slack_webhook_url), "ai_enabled": c.ai_enabled,
    }
    if admin and c.slack_webhook_url:
        url = decrypt(c.slack_webhook_url) or ""
        out["slack_webhook_hint"] = (url[:28] + "…" + url[-4:]) if url else None  # never return the full secret
    return out


@router.get("/settings")
def get_settings_route(ctx: Ctx = Depends(get_ctx)):
    return _settings_out(ctx)


@router.patch("/settings")
def patch_settings(body: SettingsPatch, ctx: Ctx = Depends(require("settings.manage"))):
    c = ctx.company
    data = body.model_dump(exclude_unset=True)
    if data.get("name"):
        c.name = data["name"]
    if body.timezone is not None:
        if not valid_timezone(body.timezone):
            raise bad_request("invalid_timezone", "Unknown IANA timezone")
        c.timezone = body.timezone
    if body.slack_webhook_url is not None:
        if body.slack_webhook_url.scheme != "https":
            raise bad_request("invalid_webhook", "Slack webhook must use https")
        c.slack_webhook_url = encrypt(str(body.slack_webhook_url))
    if body.clear_slack:
        c.slack_webhook_url = None
    if body.report_email_enabled is False:
        c.report_email_day = None
    elif body.report_email_day is not None:
        c.report_email_day = body.report_email_day
    elif body.report_email_enabled and c.report_email_day is None:
        c.report_email_day = 0
    if body.ai_enabled is not None:  # company kill switch: reports fall back to built-in wording within 60 s, no restart
        c.ai_enabled = body.ai_enabled
    if body.email_domain is not None:
        domain = body.email_domain.lower().strip()
        if domain in PUBLIC_DOMAINS or "." not in domain or not ctx.me.email.lower().endswith("@" + domain):
            raise bad_request("invalid_domain", "Domain must be a company domain that your own email belongs to")
        taken = ctx.db.execute(text("SELECT id FROM auth_company_by_domain(:d)"), {"d": domain}).first()
        if taken and taken.id != c.id:
            raise conflict("domain_taken", "Another company already uses this domain")
        c.email_domain = domain
    ctx.db.commit()
    return _settings_out(ctx)


@router.get("/notifications")
def notification_log(status: str | None = None, ctx: Ctx = Depends(require("settings.manage")), page: Page = Depends(pagination)):
    stmt = select(NotificationLog).order_by(NotificationLog.sent_at.desc())
    if status:
        stmt = stmt.where(NotificationLog.status == status)
    return paged(
        ctx.db, stmt, page,
        lambda n: {
            "id": str(n.id), "user_id": str(n.user_id) if n.user_id else None, "kind": n.kind, "channel": n.channel,
            "status": n.status, "error": n.error, "sent_at": n.sent_at.isoformat(),
        },
    )


# --------------------------------------------------------------------------- task fields
class FieldIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    label: str = Field(min_length=1, max_length=80)
    type: str = Field(pattern="^(text|number|date|select)$")
    options: list[str] = []
    required: bool = False


class FieldPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    options: list[str] | None = None
    required: bool | None = None
    is_active: bool | None = None


def field_out(f: TaskFieldDefinition) -> dict:
    return {
        "id": str(f.id), "key": f.key, "label": f.label, "type": f.type, "options": f.options,
        "required": f.required, "is_active": f.is_active, "is_builtin": f.is_builtin,
    }


@router.get("/task-fields")
def list_task_fields(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(
        select(TaskFieldDefinition).order_by(TaskFieldDefinition.is_builtin.desc(), TaskFieldDefinition.created_at)
    ).scalars()
    return {"items": [field_out(f) for f in rows]}


@router.post("/task-fields", status_code=201)
def create_task_field(body: FieldIn, ctx: Ctx = Depends(require("settings.manage"))):
    if body.type == "select" and not body.options:
        raise bad_request("options_required", "Select fields need at least one option")
    if ctx.db.execute(select(TaskFieldDefinition.id).where(TaskFieldDefinition.key == body.key)).first():
        raise conflict("field_exists", "A field with this key already exists")
    f = TaskFieldDefinition(company_id=ctx.company_id, **body.model_dump())
    ctx.db.add(f)
    ctx.db.commit()
    return field_out(f)


@router.patch("/task-fields/{field_id}")
def patch_task_field(field_id: uuid.UUID, body: FieldPatch, ctx: Ctx = Depends(require("settings.manage"))):
    f = ctx.db.get(TaskFieldDefinition, field_id)
    if not f:
        raise not_found("Task field")
    data = body.model_dump(exclude_unset=True)
    if f.is_builtin and set(data) - {"is_active", "label", "options"}:
        raise bad_request("builtin_field", "Built-in fields can only be hidden, relabelled or get new options")
    for k, v in data.items():
        if v is not None:
            setattr(f, k, v)
    ctx.db.commit()
    return field_out(f)
