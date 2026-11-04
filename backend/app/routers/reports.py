"""Base reports (on-screen + export), client report templates, AI-drafted runs, sharing, public page."""

import uuid
from datetime import UTC, date, datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from ..db import new_session
from ..deps import Ctx, Page, get_ctx, paged, pagination, require, require_any
from ..errors import ApiError, bad_request, conflict, forbidden, not_found
from ..models import (
    Client,
    ClientContact,
    Company,
    ReportRun,
    ReportShare,
    ReportTemplate,
    User,
)
from ..reports import REGISTRY
from ..reports.base import ReportContext
from ..reports.render import render_report_html
from ..security import decode_token, make_file_token, new_share_token
from ..services import jobs, runs, storage
from ..services.dashboard import effective_user_ids
from ..services.timeutil import company_today

router = APIRouter(tags=["reports"])
CLIENT_REPORT_KEYS = ("report.template.manage", "report.ai.draft", "report.approve", "report.share.client")
FORMATS = ("pdf", "xlsx", "docx")
MEDIA = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _defn(key: str):
    d = REGISTRY.get(key)
    if d is None:
        raise not_found("Report")
    return d


def _check_report_access(ctx: Ctx, key: str):
    d = _defn(key)
    if ctx.scope_of(d.required_permission) is None:
        raise forbidden("You do not have access to this report")
    return d


# --------------------------------------------------------------------------- base reports
@router.get("/reports")
def list_reports(ctx: Ctx = Depends(get_ctx)):
    today = company_today(ctx.company.timezone)
    items = []
    for d in REGISTRY.values():
        scope = ctx.scope_of(d.required_permission)
        if scope:
            start, end = d.default_period(today)
            items.append({"key": d.key, "title": d.title, "scope": scope,
                          "default_from": start.isoformat(), "default_to": end.isoformat()})
    return {"items": items}


def _build_context(ctx: Ctx, d, start: date | None, end: date | None, project, user) -> ReportContext:
    today = company_today(ctx.company.timezone)
    d_start, d_end = d.default_period(today)
    start, end = start or d_start, end or d_end
    if end < start or (end - start).days > 400:
        raise bad_request("invalid_range", "Choose a valid date range of at most 400 days")
    uids = effective_user_ids(ctx.visible(d.required_permission), user)
    return ReportContext(db=ctx.db, start=start, end=end, today=today, scope_user_ids=uids, project_id=project)


@router.get("/reports/{key}")
def get_report(
    key: str, from_: date | None = Query(default=None, alias="from"), to: date | None = None,
    project: uuid.UUID | None = None, user: uuid.UUID | None = None, ctx: Ctx = Depends(get_ctx),
):
    d = _check_report_access(ctx, key)
    rc = _build_context(ctx, d, from_, to, project, user)
    figures = d.query(rc)
    html = render_report_html(key, figures, ctx.company.name)
    return {"key": key, "title": d.title, "figures": figures, "html": html}


class ExportIn(BaseModel):
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    project: uuid.UUID | None = None
    user: uuid.UUID | None = None


@router.post("/reports/{key}/export", status_code=202)
def export_report(key: str, body: ExportIn | None = None, format: str = "pdf", ctx: Ctx = Depends(get_ctx)):
    d = _check_report_access(ctx, key)
    if format not in FORMATS:
        raise bad_request("invalid_format", f"format must be one of {', '.join(FORMATS)}")
    body = body or ExportIn()
    rc = _build_context(ctx, d, body.from_, body.to, body.project, body.user)
    run = ReportRun(
        company_id=ctx.company_id, report_key=key, period_start=rc.start, period_end=rc.end, requested_by=ctx.me.id,
        export_format=format, status="queued",
        scope_user_ids=None if rc.scope_user_ids is None else [str(u) for u in rc.scope_user_ids],
        params={"project": str(body.project) if body.project else None, "user": str(body.user) if body.user else None},
    )
    ctx.db.add(run)
    ctx.db.flush()
    jobs.enqueue(ctx.db, "report.generate", ctx.company_id, {"run_id": str(run.id)})
    ctx.db.commit()
    return {"id": str(run.id), "status": run.status}


# --------------------------------------------------------------------------- run serialization
def _is_client_run(run: ReportRun) -> bool:
    tpl = run.params.get("template") if run.params else None
    return bool(tpl and tpl["audience"] == "client")


def _run_access(ctx: Ctx, run: ReportRun) -> None:
    """Client-facing runs are visible to people who work on client reports; every other run (plain exports,
    internal templates) is scoped to its requester's own visibility, so only the requester may open it."""
    if run.requested_by == ctx.me.id or (_is_client_run(run) and any(ctx.has(k) for k in CLIENT_REPORT_KEYS)):
        return
    raise forbidden("You cannot access this report run")


def _file_urls(run: ReportRun) -> dict[str, str | None]:
    out = {}
    for fmt in FORMATS:
        key = getattr(run, f"file_url_{fmt}")
        out[fmt] = f"/api/v1/files/{make_file_token(key, 3600)}" if key else None  # signed, valid 1 hour
    return out


def _run_out(run: ReportRun, detail: bool = False, template_name: str | None = None) -> dict:
    tpl = run.params.get("template") if run.params else None
    out = {
        "id": str(run.id), "report_key": run.report_key, "status": run.status, "export_format": run.export_format,
        "title": tpl["name"] if tpl else REGISTRY[run.report_key].title,
        "template_id": str(run.template_id) if run.template_id else None,
        "audience": tpl["audience"] if tpl else None,
        "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(),
        "requested_by": str(run.requested_by) if run.requested_by else None,
        "approved_by": str(run.approved_by) if run.approved_by else None,
        "approved_at": run.approved_at.isoformat() if run.approved_at else None,
        "ai_provider": run.ai_provider, "error": run.error, "created_at": run.created_at.isoformat(),
        "downloads": _file_urls(run),
        "client_id": tpl.get("client_id") if tpl else None,
        "person_filter": (run.params or {}).get("user"),
    }
    if detail:
        out.update({
            "figures": run.figures, "ai_text": run.ai_text, "sections": tpl["sections"] if tpl else [],
            "tone_instructions": tpl["tone_instructions"] if tpl else None, "redraft_note": run.redraft_note,
        })
    return out


@router.get("/report-runs/{run_id}")
def get_run(run_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    run = ctx.db.get(ReportRun, run_id)
    if not run:
        raise not_found("Report run")
    _run_access(ctx, run)
    return _run_out(run, detail=True)


@router.get("/report-runs/{run_id}/preview")
def preview_run(run_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    """The exact HTML that goes into the PDF / shared page, rendered from the stored figures and current draft text."""
    run = ctx.db.get(ReportRun, run_id)
    if not run:
        raise not_found("Report run")
    _run_access(ctx, run)
    if run.figures is None:
        raise conflict("not_ready", "The report has not been generated yet")
    return {"html": runs.render_run_html(ctx.db, run, ctx.company)}


@router.get("/report-runs")
def list_runs(
    template: uuid.UUID | None = None, status: str | None = None, kind: str | None = None,
    ctx: Ctx = Depends(get_ctx), page: Page = Depends(pagination),
):
    stmt = select(ReportRun).order_by(ReportRun.created_at.desc())
    mine = ReportRun.requested_by == ctx.me.id
    if any(ctx.has(k) for k in CLIENT_REPORT_KEYS):
        stmt = stmt.where(mine | (ReportRun.params["template"]["audience"].astext == "client"))
    else:
        stmt = stmt.where(mine)
    if template:
        stmt = stmt.where(ReportRun.template_id == template)
    if status:
        stmt = stmt.where(ReportRun.status == status)
    if kind == "client":
        stmt = stmt.where(ReportRun.template_id.is_not(None))
    elif kind == "export":
        stmt = stmt.where(ReportRun.template_id.is_(None))
    return paged(ctx.db, stmt, page, _run_out)


# --------------------------------------------------------------------------- templates
class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    audience: str = Field(default="client", pattern="^(internal|client)$")
    base_report: str = "weekly"
    format: str = Field(default="narrative", pattern="^(narrative|bullet_summary|table_commentary)$")
    sections: list[str] = Field(default_factory=list, max_length=12)
    tone_instructions: str = Field(default="", max_length=2000)
    client_id: uuid.UUID | None = None
    schedule: str = Field(default="none", pattern="^(weekly|monthly|none)$")


class TemplatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    audience: str | None = Field(default=None, pattern="^(internal|client)$")
    base_report: str | None = None
    format: str | None = Field(default=None, pattern="^(narrative|bullet_summary|table_commentary)$")
    sections: list[str] | None = Field(default=None, max_length=12)
    tone_instructions: str | None = Field(default=None, max_length=2000)
    client_id: uuid.UUID | None = None
    schedule: str | None = Field(default=None, pattern="^(weekly|monthly|none)$")


def _tpl_out(t: ReportTemplate, client_name: str | None = None) -> dict:
    return {
        "id": str(t.id), "name": t.name, "audience": t.audience, "base_report": t.base_report, "format": t.format,
        "sections": t.sections, "tone_instructions": t.tone_instructions,
        "client_id": str(t.client_id) if t.client_id else None, "client_name": client_name, "schedule": t.schedule,
    }


def _validate_template(ctx: Ctx, audience: str, base_report: str, sections: list[str], client_id) -> list[str]:
    d = REGISTRY.get(base_report)
    if d is None:
        raise bad_request("invalid_base_report", f"Unknown base report '{base_report}'")
    if audience == "client":
        if not d.client_safe:
            raise bad_request("invalid_base_report", "Client reports cannot be built on individual performance figures")
        if client_id is None:
            raise bad_request("client_required", "Client-facing templates need a client")
    if client_id is not None and not ctx.db.get(Client, client_id):
        raise bad_request("invalid_client", "Client does not exist")
    clean = [s.strip() for s in sections if s.strip()]
    if not clean:
        raise bad_request("sections_required", "Add at least one section")
    if len(set(clean)) != len(clean):
        raise bad_request("duplicate_sections", "Section names must be unique")
    return clean


@router.get("/report-templates")
def list_templates(ctx: Ctx = Depends(require_any(*CLIENT_REPORT_KEYS))):
    rows = ctx.db.execute(
        select(ReportTemplate, Client.name).outerjoin(Client, Client.id == ReportTemplate.client_id).order_by(ReportTemplate.name)
    ).all()
    return {"items": [_tpl_out(t, cn) for t, cn in rows]}


@router.post("/report-templates", status_code=201)
def create_template(body: TemplateIn, ctx: Ctx = Depends(require("report.template.manage"))):
    sections = _validate_template(ctx, body.audience, body.base_report, body.sections, body.client_id)
    t = ReportTemplate(company_id=ctx.company_id, **{**body.model_dump(), "sections": sections})
    ctx.db.add(t)
    ctx.db.commit()
    return _tpl_out(t)


@router.patch("/report-templates/{template_id}")
def patch_template(template_id: uuid.UUID, body: TemplatePatch, ctx: Ctx = Depends(require("report.template.manage"))):
    t = ctx.db.get(ReportTemplate, template_id)
    if not t:
        raise not_found("Template")
    data = body.model_dump(exclude_unset=True)
    merged = {
        "audience": t.audience, "base_report": t.base_report, "sections": list(t.sections),
        "client_id": t.client_id, **{k: v for k, v in data.items() if k in ("audience", "base_report", "sections", "client_id")},
    }
    merged["sections"] = _validate_template(ctx, merged["audience"], merged["base_report"], merged["sections"], merged["client_id"])
    for k, v in data.items():
        if v is None and k != "client_id":
            continue
        setattr(t, k, merged["sections"] if k == "sections" else v)
    ctx.db.commit()
    return _tpl_out(t)


@router.delete("/report-templates/{template_id}", status_code=204)
def delete_template(template_id: uuid.UUID, ctx: Ctx = Depends(require("report.template.manage"))):
    t = ctx.db.get(ReportTemplate, template_id)
    if not t:
        raise not_found("Template")
    ctx.db.delete(t)
    ctx.db.commit()


class GenerateIn(BaseModel):
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    user: uuid.UUID | None = None  # optional: only work by this person (never named in client text or sent to the AI)


@router.post("/report-templates/{template_id}/generate", status_code=202)
def generate_from_template(template_id: uuid.UUID, body: GenerateIn | None = None, ctx: Ctx = Depends(require("report.ai.draft"))):
    t = ctx.db.get(ReportTemplate, template_id)
    if not t:
        raise not_found("Template")
    d = REGISTRY[t.base_report]
    scope = None
    if t.audience == "internal":  # internal reports are limited to what the requester may see
        if ctx.scope_of(d.required_permission) is None:
            raise forbidden("You do not have access to this base report")
        ids = ctx.visible(d.required_permission)
        scope = None if ids is None else [str(i) for i in ids]
    today = company_today(ctx.company.timezone)
    body = body or GenerateIn()
    start, end = (body.from_, body.to) if body.from_ and body.to else runs.previous_full_period(t.base_report, today)
    if end < start or (end - start).days > 400:
        raise bad_request("invalid_range", "Choose a valid date range of at most 400 days")
    if body.user and not ctx.db.get(User, body.user):
        raise bad_request("invalid_user", "Person does not exist")
    run = ReportRun(
        company_id=ctx.company_id, template_id=t.id, report_key=t.base_report, period_start=start, period_end=end,
        requested_by=ctx.me.id, status="queued", scope_user_ids=scope,
        params={"template": runs.template_snapshot(t), "user": str(body.user) if body.user else None},
    )
    ctx.db.add(run)
    ctx.db.flush()
    jobs.enqueue(ctx.db, "report.draft", ctx.company_id, {"run_id": str(run.id)})
    ctx.db.commit()
    return {"id": str(run.id), "status": run.status}


# --------------------------------------------------------------------------- run workflow
def _client_run(ctx: Ctx, run_id: uuid.UUID) -> ReportRun:
    run = ctx.db.get(ReportRun, run_id)
    if not run or not run.params.get("template"):
        raise not_found("Report run")
    return run


class DraftPatch(BaseModel):
    ai_text: dict[str, str]


@router.patch("/report-runs/{run_id}")
def edit_draft(run_id: uuid.UUID, body: DraftPatch, ctx: Ctx = Depends(require_any("report.ai.draft", "report.approve"))):
    run = _client_run(ctx, run_id)
    if run.status != "drafted":
        raise conflict("not_editable", "Only drafts that are awaiting approval can be edited")
    allowed = set(run.params["template"]["sections"])
    unknown = set(body.ai_text) - allowed
    if unknown:
        raise bad_request("unknown_section", f"Unknown sections: {', '.join(sorted(unknown))}")
    run.ai_text = {**(run.ai_text or {}), **body.ai_text}
    ctx.db.commit()
    return _run_out(run, detail=True)


class RedraftIn(BaseModel):
    note: str = Field(default="", max_length=500)
    figures_only: bool = False


@router.post("/report-runs/{run_id}/redraft", status_code=202)
def redraft(run_id: uuid.UUID, body: RedraftIn | None = None, ctx: Ctx = Depends(require("report.ai.draft"))):
    run = _client_run(ctx, run_id)
    if run.status not in ("drafted", "failed"):
        raise conflict("not_redraftable", "This run cannot be redrafted in its current state")
    body = body or RedraftIn()
    run.redraft_note, run.status, run.error = body.note or None, "queued", None
    jobs.enqueue(ctx.db, "report.draft", ctx.company_id, {"run_id": str(run.id), "figures_only": body.figures_only, "recompute": False})
    ctx.db.commit()
    return {"id": str(run.id), "status": run.status}


@router.post("/report-runs/{run_id}/approve")
def approve(run_id: uuid.UUID, ctx: Ctx = Depends(require("report.approve"))):
    run = _client_run(ctx, run_id)
    if run.status != "drafted":
        raise conflict("not_approvable", "Only drafted reports can be approved")
    if run.params["template"]["audience"] != "client":
        raise conflict("not_approvable", "Internal reports do not need approval")
    run.status, run.approved_by, run.approved_at = "approved", ctx.me.id, datetime.now(UTC)
    jobs.enqueue(ctx.db, "report.finalize", ctx.company_id, {"run_id": str(run.id)})
    ctx.db.commit()
    return _run_out(run, detail=True)


class ShareIn(BaseModel):
    contact_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    expires_in_days: int = Field(default=30, ge=1, le=90)


def _share_out(s: ReportShare) -> dict:
    return {
        "id": str(s.id), "recipient_email": s.recipient_email, "expires_at": s.expires_at.isoformat(),
        "viewed_at": s.viewed_at.isoformat() if s.viewed_at else None,
        "emailed_at": s.emailed_at.isoformat() if s.emailed_at else None,
        "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
    }


@router.post("/report-runs/{run_id}/share", status_code=201)
def share(run_id: uuid.UUID, body: ShareIn, ctx: Ctx = Depends(require("report.share.client"))):
    run = _client_run(ctx, run_id)
    if run.status not in ("approved", "sent") or run.approved_by is None:
        raise conflict("not_approved", "Only approved reports can be shared with a client")
    client_id = uuid.UUID(run.params["template"]["client_id"])
    contacts = ctx.db.execute(
        select(ClientContact).where(ClientContact.client_id == client_id, ClientContact.id.in_(body.contact_ids))
    ).scalars().all()
    if len(contacts) != len(set(body.contact_ids)):
        raise bad_request("invalid_contact", "Recipients must be contacts of this report's client")
    expires = datetime.now(UTC) + timedelta(days=body.expires_in_days)
    shares = [
        ReportShare(company_id=ctx.company_id, report_run_id=run.id, client_id=client_id, recipient_email=c.email,
                    token=new_share_token(), expires_at=expires)
        for c in contacts
    ]
    ctx.db.add_all(shares)
    ctx.db.flush()
    jobs.enqueue(ctx.db, "report.share", ctx.company_id, {"run_id": str(run.id)})
    ctx.db.commit()
    return {"items": [_share_out(s) for s in shares]}


@router.get("/report-runs/{run_id}/shares")
def list_shares(run_id: uuid.UUID, ctx: Ctx = Depends(require_any("report.share.client", "report.approve"))):
    _client_run(ctx, run_id)
    rows = ctx.db.execute(select(ReportShare).where(ReportShare.report_run_id == run_id).order_by(ReportShare.created_at.desc())).scalars()
    return {"items": [_share_out(s) for s in rows]}


@router.delete("/report-runs/{run_id}/shares/{share_id}", status_code=204)
def revoke_share(run_id: uuid.UUID, share_id: uuid.UUID, ctx: Ctx = Depends(require("report.share.client"))):
    s = ctx.db.get(ReportShare, share_id)
    if not s or s.report_run_id != run_id:
        raise not_found("Share")
    s.revoked_at = s.revoked_at or datetime.now(UTC)
    ctx.db.commit()


# --------------------------------------------------------------------------- signed file download
@router.get("/files/{token}")
def download_file(token: str):
    try:
        key = decode_token(token, "file")["key"]
        data = storage.get(key)
    except (jwt.PyJWTError, KeyError, ValueError, FileNotFoundError):
        raise ApiError(404, "not_found", "Link is invalid or expired") from None
    fmt = key.rsplit(".", 1)[-1]
    return Response(data, media_type=MEDIA.get(fmt, "application/octet-stream"),
                    headers={"Content-Disposition": f'attachment; filename="report.{fmt}"'})


# --------------------------------------------------------------------------- shared (no login)
shared_router = APIRouter(tags=["shared"])


def _open_share(token: str, mark_viewed: bool):
    anon = new_session()
    try:
        row = anon.execute(text("SELECT * FROM shared_share_by_token(:t)"), {"t": token}).first()
    finally:
        anon.close()
    if not row:
        raise ApiError(404, "not_found", "This link is not valid")
    db = new_session(row.company_id)
    share = db.get(ReportShare, row.id)
    now = datetime.now(UTC)
    if share is None or share.revoked_at is not None or share.expires_at < now:
        db.close()
        raise ApiError(410, "link_expired", "This link has expired or was revoked")
    if mark_viewed and share.viewed_at is None:
        share.viewed_at = now
        db.commit()
    return db, share


@shared_router.get("/shared/{token}")
def shared_report(token: str):
    db, share = _open_share(token, mark_viewed=True)
    try:
        run = db.get(ReportRun, share.report_run_id)
        company = db.get(Company, run.company_id)
        html = runs.render_run_html(db, run, company)
        return {
            "title": runs.run_title(run), "company_name": company.name, "client_name": runs.client_name_for(db, run),
            "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(),
            "expires_at": share.expires_at.isoformat(), "html": html,
            "pdf_url": f"/api/v1/shared/{token}/pdf" if run.file_url_pdf else None,
        }
    finally:
        db.close()


@shared_router.get("/shared/{token}/pdf")
def shared_pdf(token: str):
    db, share = _open_share(token, mark_viewed=False)
    try:
        run = db.get(ReportRun, share.report_run_id)
        if not run.file_url_pdf:
            raise not_found("PDF")
        data = storage.get(run.file_url_pdf)
    finally:
        db.close()
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="report.pdf"'})


