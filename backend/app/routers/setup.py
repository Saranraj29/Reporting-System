"""Projects, clients (+contacts), company settings and task-field definitions."""

import uuid
from datetime import date
from datetime import time as dtime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from sqlalchemy import delete, func, select, text

from ..config import get_settings
from ..deps import Ctx, Page, get_ctx, paged, pagination, require, require_any
from ..errors import ApiError, bad_request, conflict, not_found
from ..models import (
    Client,
    ClientContact,
    NotificationLog,
    Project,
    ProjectMember,
    ReportTemplate,
    Role,
    Task,
    TaskFieldDefinition,
    Team,
    TeamMember,
    TimeEntry,
    User,
)
from ..security import decrypt, encrypt
from ..services import reminders
from ..services.access import task_project_ids, visible_project_ids
from ..services.dashboard import clear_dashboard_cache
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


def _join_team(ctx: Ctx, team_id: uuid.UUID | None, user_ids) -> None:
    """People who work on a project belong to the project's team: add the ones who are not members of it yet (nobody is ever removed)."""
    if not team_id or not user_ids:
        return
    already = set(ctx.db.execute(select(TeamMember.user_id).where(TeamMember.team_id == team_id, TeamMember.user_id.in_(user_ids))).scalars())
    ctx.db.add_all(TeamMember(company_id=ctx.company_id, team_id=team_id, user_id=u) for u in set(user_ids) - already)


def _team_name(ctx: Ctx, team_id: uuid.UUID | None) -> str | None:
    return ctx.db.execute(select(Team.name).where(Team.id == team_id)).scalar_one_or_none() if team_id else None


@router.get("/projects")
def list_projects(
    status: str | None = None, client_id: uuid.UUID | None = None, team: uuid.UUID | None = None, q: str | None = None,
    ctx: Ctx = Depends(get_ctx), page: Page = Depends(pagination),
):
    stmt = (select(Project, Client.name, Team.name).outerjoin(Client, Client.id == Project.client_id)
            .outerjoin(Team, Team.id == Project.team_id).order_by(Project.name))
    visible = visible_project_ids(ctx.db, ctx.me.id, ctx.perms)  # people see the projects that concern them, not every project of the company
    if visible is not None:
        stmt = stmt.where(Project.id.in_(visible))
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
    scope = ctx.scope_of("task.edit")
    addable = task_project_ids(ctx.db, ctx.me.id, scope) if scope else set()  # None = every project
    return {
        "items": [{**_project_out(p, cn, members.get(p.id), owners.get(p.id), tn), "can_add_tasks": addable is None or p.id in addable}
                  for p, cn, tn in rows],
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
    team_changed = data.get("team_id") and data["team_id"] != p.team_id
    for k, v in data.items():
        if k in ("name", "status") and v is None:
            continue
        setattr(p, k, v)
    if team_changed:  # a project moved to a team brings its current members along
        _join_team(ctx, p.team_id, [u for ids in _members(ctx, [p.id]).values() for u in map(uuid.UUID, ids)])
    ctx.db.commit()
    return _project_out(p, members=_members(ctx, [p.id]).get(p.id), owners=_members(ctx, [p.id], owners_only=True).get(p.id), team_name=_team_name(ctx, p.team_id))


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: uuid.UUID, force: bool = False, ctx: Ctx = Depends(require("project.manage"))):
    """Delete a project with everything in it (tasks, comments, time entries). A project that has tasks needs the person to confirm (force);
    archiving keeps the history and is the gentler choice."""
    project = ctx.db.get(Project, project_id)
    if not project:
        raise not_found("Project")
    n = ctx.db.execute(select(func.count()).select_from(Task).where(Task.project_id == project.id)).scalar_one()
    hours = ctx.db.execute(select(func.coalesce(func.sum(TimeEntry.hours), 0)).join(Task, Task.id == TimeEntry.task_id).where(Task.project_id == project.id)).scalar_one()
    if n and not force:
        raise ApiError(409, "in_use", f"{project.name} has {n} task{'s' if n != 1 else ''} and {float(hours):g} h logged. Deleting removes them permanently; "
                       "archiving the project keeps them.", {"tasks": n, "hours": float(hours)})
    ctx.db.delete(project)
    ctx.db.commit()
    clear_dashboard_cache()


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
    project = ctx.db.get(Project, project_id)
    if not project:
        raise not_found("Project")
    owners = set(body.owner_ids)
    ids = set(body.user_ids) | owners
    if ids and ctx.db.execute(select(func.count()).select_from(User).where(User.id.in_(ids))).scalar_one() != len(ids):
        raise bad_request("invalid_user", "One or more users do not exist")
    ctx.db.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id))
    ctx.db.add_all(ProjectMember(company_id=ctx.company_id, project_id=project_id, user_id=u, is_owner=u in owners) for u in ids)
    _join_team(ctx, project.team_id, ids)  # added to the project = added to its team
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


@router.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: uuid.UUID, force: bool = False, ctx: Ctx = Depends(require("project.manage"))):
    """Delete a client and its contacts. Its projects are kept (without a client); its report templates are deleted. With either, the person must confirm (force)."""
    client = ctx.db.get(Client, client_id)
    if not client:
        raise not_found("Client")
    projects = ctx.db.execute(select(func.count()).select_from(Project).where(Project.client_id == client.id)).scalar_one()
    templates = ctx.db.execute(select(func.count()).select_from(ReportTemplate).where(ReportTemplate.client_id == client.id)).scalar_one()
    if (projects or templates) and not force:
        raise ApiError(409, "in_use", f"{client.name} has {projects} project{'s' if projects != 1 else ''} (kept, without a client) and "
                       f"{templates} report template{'s' if templates != 1 else ''} (deleted).", {"projects": projects, "templates": templates})
    ctx.db.execute(delete(ReportTemplate).where(ReportTemplate.client_id == client.id))
    ctx.db.delete(client)
    ctx.db.commit()


@router.delete("/clients/{client_id}/contacts/{contact_id}", status_code=204)
def delete_contact(client_id: uuid.UUID, contact_id: uuid.UUID, ctx: Ctx = Depends(require("project.manage"))):
    c = ctx.db.get(ClientContact, contact_id)
    if not c or c.client_id != client_id:
        raise not_found("Contact")
    ctx.db.delete(c)
    ctx.db.commit()


# --------------------------------------------------------------------------- settings
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class SettingsPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    slack_webhook_url: HttpUrl | None = None
    clear_slack: bool = False
    report_email_day: int | None = Field(default=None, ge=0, le=6)
    report_email_enabled: bool | None = None
    timezone: str | None = None
    email_domain: str | None = None
    ai_enabled: bool | None = None
    reminders_enabled: bool | None = None
    reminder_morning_time: str | None = Field(default=None, pattern=HHMM)
    reminder_eod_time: str | None = Field(default=None, pattern=HHMM)
    reminder_due_time: str | None = Field(default=None, pattern=HHMM)


def _hhmm(t: dtime) -> str:
    return t.strftime("%H:%M")


def _settings_out(ctx: Ctx) -> dict:
    c = ctx.company
    admin = ctx.has("settings.manage")
    out = {
        "name": c.name, "timezone": c.timezone, "email_domain": c.email_domain,
        "report_email_enabled": c.report_email_day is not None, "report_email_day": c.report_email_day,
        "slack_configured": bool(c.slack_webhook_url), "ai_enabled": c.ai_enabled,
        "reminders_enabled": c.reminders_enabled, "reminder_morning_time": _hhmm(c.reminder_morning_time),
        "reminder_eod_time": _hhmm(c.reminder_eod_time), "reminder_due_time": _hhmm(c.reminder_due_time),
    }
    if admin and c.slack_webhook_url:
        url = decrypt(c.slack_webhook_url) or ""
        out["slack_webhook_hint"] = (url[:28] + "…" + url[-4:]) if url else None  # never return the full secret
    if admin:  # how e-mail leaves the system; the password is never part of this
        from ..services import mail

        st = get_settings()
        out["email"] = {
            "backend": st.email_backend, "from": st.email_from, "host": st.smtp_host if st.email_backend == "smtp" else None,
            "port": st.smtp_port if st.email_backend == "smtp" else None, "security": st.smtp_security if st.email_backend == "smtp" else None,
            "problems": mail.config_problems(),
        }
    return out


@router.get("/settings")
def get_settings_route(ctx: Ctx = Depends(get_ctx)):
    return _settings_out(ctx)


@router.post("/settings/test-email")
def test_email(ctx: Ctx = Depends(require("settings.manage"))):
    """Sends a test message to the admin's own address, right now, so a wrong host / password / sender is found in seconds (not after a user waits)."""
    from ..services import mail, mail_templates

    st = get_settings()
    subject, text, html = mail_templates.test_email(ctx.company.name)
    try:
        mail.send_email(ctx.me.email, subject, text, html)
    except mail.MailError as exc:
        raise ApiError(502, "email_failed", str(exc)) from None
    if st.email_backend == "console":
        return {"ok": True, "delivered": False, "message": "Development mode: the email was written to the server log, not delivered. Set EMAIL_BACKEND=smtp to send real email."}
    return {"ok": True, "delivered": True, "message": f"A test email was sent to {ctx.me.email}. Check the inbox (and the spam folder)."}


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
    morning = dtime.fromisoformat(body.reminder_morning_time) if body.reminder_morning_time else c.reminder_morning_time
    eod = dtime.fromisoformat(body.reminder_eod_time) if body.reminder_eod_time else c.reminder_eod_time
    if body.reminder_morning_time or body.reminder_eod_time:
        if morning >= eod:
            raise bad_request("invalid_reminder_times", "The morning reminder must be earlier than the end-of-day reminder")
    if body.reminders_enabled is not None:
        c.reminders_enabled = body.reminders_enabled
    if body.reminder_morning_time:
        c.reminder_morning_time = morning
    if body.reminder_eod_time:
        c.reminder_eod_time = eod
    if body.reminder_due_time:
        c.reminder_due_time = dtime.fromisoformat(body.reminder_due_time)
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


# --------------------------------------------------------------------------- reminders (wording, roles, times)
def _reminder_out(c, kind: str) -> dict:
    d = reminders.KINDS[kind]
    cfg = (c.reminder_config or {}).get(kind) or {}
    return {
        "kind": kind, "label": d["label"], "description": d["description"], "placeholders": d["placeholders"],
        "time": _hhmm(getattr(c, d["time"])) if d["time"] else None,
        "subject": cfg.get("subject") or d["subject"], "body": cfg.get("body") or d["body"],
        "default_subject": d["subject"], "default_body": d["body"],
        "roles_off": sorted(reminders.roles_off(c, kind)),
    }


@router.get("/settings/reminders")
def get_reminders(ctx: Ctx = Depends(require("settings.manage"))):
    c = ctx.company
    roles = ctx.db.execute(select(Role.id, Role.name).order_by(Role.name)).all()
    return {
        "reminders_enabled": c.reminders_enabled,
        "roles": [{"id": str(r.id), "name": r.name} for r in roles],
        "kinds": [_reminder_out(c, k) for k in reminders.KINDS],
    }


class ReminderIn(BaseModel):
    subject: str | None = Field(default=None, max_length=reminders.MAX_SUBJECT)
    body: str | None = Field(default=None, max_length=reminders.MAX_BODY)
    roles_off: list[uuid.UUID] = Field(default_factory=list, max_length=200)  # roles that do NOT receive this reminder
    time: str | None = Field(default=None, pattern=HHMM)


@router.put("/settings/reminders/{kind}")
def put_reminder(kind: str, body: ReminderIn, ctx: Ctx = Depends(require("settings.manage"))):
    """Wording, role switches and (for the timed ones) the send time of one reminder. Empty or default wording is stored as 'not customised'."""
    if kind not in reminders.KINDS:
        raise not_found("Reminder")
    d, c = reminders.KINDS[kind], ctx.company
    subject, text_ = (body.subject or "").strip(), (body.body or "").strip()
    bad = reminders.unknown_placeholders(kind, subject, text_)
    if bad:
        raise bad_request("unknown_placeholder", f"Unknown placeholder {', '.join('{' + b + '}' for b in bad)}; use {', '.join('{' + n + '}' for n in d['placeholders'])}")
    known = set(ctx.db.execute(select(Role.id)).scalars())
    if not set(body.roles_off) <= known:
        raise bad_request("invalid_role", "Unknown role")
    if body.time:
        if not d["time"]:
            raise bad_request("no_time", "This reminder has no send time of its own")
        new = dtime.fromisoformat(body.time)
        morning = new if d["time"] == "reminder_morning_time" else c.reminder_morning_time
        eod = new if d["time"] == "reminder_eod_time" else c.reminder_eod_time
        if morning >= eod:
            raise bad_request("invalid_reminder_times", "The morning reminder must be earlier than the end-of-day reminder")
        setattr(c, d["time"], new)
    entry = {}
    if subject and subject != d["subject"]:
        entry["subject"] = subject
    if text_ and text_ != d["body"]:
        entry["body"] = text_
    if body.roles_off:
        entry["roles_off"] = sorted({str(r) for r in body.roles_off})
    config = {k: v for k, v in (c.reminder_config or {}).items() if k != kind}
    if entry:
        config[kind] = entry
    c.reminder_config = config  # a new dict, so the change is noticed
    ctx.db.commit()
    return _reminder_out(c, kind)


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
