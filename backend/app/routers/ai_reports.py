"""AI reports: ask for a report -> review the STRUCTURE -> approve -> get the report (.md / .pdf / .docx / .xlsx).
For the company's own managers: project owners (their projects), admins, CTO. No client approval, no sharing."""

import re
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..ai import policy
from ..deps import Ctx, get_ctx
from ..errors import ApiError, bad_request, conflict, forbidden, not_found
from ..models import AiFeedback, AiReport, Project, ProjectMember, User
from ..reports.render import markdown_to_html
from ..security import make_file_token
from ..services import jobs
from ..services.access import owned_project_ids
from ..services.airep.outline import describe
from ..services.airep.writer import SAMPLE_LIMIT

router = APIRouter(tags=["ai-reports"])
MEDIA_MD = "text/markdown; charset=utf-8"


def ai_ctx(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    if not _allowed_projects(ctx)[0] and not ctx.has("report.ai.draft"):
        raise forbidden("AI reports are available to admins, managers and project owners")
    return ctx


def _allowed_projects(ctx: Ctx) -> tuple[list[str], bool]:
    """(project ids the user may report on when restricted, unrestricted?) Key holders see every project; owners only their own."""
    if ctx.has("report.ai.draft"):
        return [], True
    return [str(p) for p in owned_project_ids(ctx.db, ctx.me.id)], False


def _row(ctx: Ctx, report_id: uuid.UUID) -> AiReport:
    row = ctx.db.get(AiReport, report_id)
    if row is None or (row.created_by != ctx.me.id and not ctx.has("report.ai.draft")):
        raise not_found("Report")
    return row


def _downloads(row: AiReport) -> dict[str, str | None]:
    return {
        fmt: (f"/api/v1/files/{make_file_token(key, 3600)}" if key else None)
        for fmt, key in (("md", row.file_url_md), ("pdf", row.file_url_pdf), ("docx", row.file_url_docx), ("xlsx", row.file_url_xlsx))
    }


def _out(ctx: Ctx, row: AiReport, detail: bool = False) -> dict:
    out = {
        "id": str(row.id), "title": row.title or "New report", "request": row.request, "status": row.status, "format_mode": row.format_mode,
        "period_start": row.period_start.isoformat(), "period_end": row.period_end.isoformat(), "error": row.error,
        "created_at": row.created_at.isoformat(), "written_by": "builtin" if row.ai_provider == "builtin" else ("ai" if row.ai_provider else None),
        "downloads": _downloads(row),
    }
    if detail:
        out["created_by"] = ctx.db.execute(select(User.name).where(User.id == row.created_by)).scalar_one_or_none() if row.created_by else None
        out["project_names"] = [p["name"] for p in (row.facts or {}).get("projects", [])]
        out["people_names"] = (row.facts or {}).get("people_filter", [])
        out["no_activity"] = (row.facts or {}).get("no_activity", [])
        out["outline"] = None if row.outline is None else {
            "title": row.outline["title"], "notes": row.outline.get("notes", ""), "sections": describe(row.outline),
            "per_project_count": sum(1 for s in row.outline["sections"] if s["scope"] == "per_project"),
        }
        out["builtin_sections"] = len((row.narrative or {}).get("_missing", [])) + len((row.verification or {}).get("failed", {}))
        out["missing_text"] = out["builtin_sections"] > 0
        vote = ctx.db.execute(select(AiFeedback.rating).where(AiFeedback.target_type == "report", AiFeedback.target_id == row.id, AiFeedback.created_by == ctx.me.id)).scalar_one_or_none()
        out["my_feedback"] = None if vote is None else ("up" if vote > 0 else "down")
    return out


# --------------------------------------------------------------------------------------------- create + list
@router.get("/ai-reports/options")
def options(ctx: Ctx = Depends(ai_ctx)):
    ids, unrestricted = _allowed_projects(ctx)
    stmt = select(Project.id, Project.name).where(Project.status != "archived").order_by(Project.name)
    if not unrestricted:
        stmt = stmt.where(Project.id.in_([uuid.UUID(i) for i in ids]))
    people = select(User.id, User.name).where(User.is_active.is_(True)).order_by(User.name)
    if not unrestricted:  # owners may only pick people working in the projects they own
        members = select(ProjectMember.user_id).where(ProjectMember.project_id.in_([uuid.UUID(i) for i in ids]))
        people = people.where(User.id.in_(members))
    return {
        "projects": [{"id": str(i), "name": n} for i, n in ctx.db.execute(stmt)],
        "people": [{"id": str(i), "name": n} for i, n in ctx.db.execute(people)],
        "all_projects": unrestricted, "ai_enabled": policy.unavailable_reason(ctx.company_id) is None, "ai_status": policy.unavailable_reason(ctx.company_id) or "ready", "max_sample_chars": SAMPLE_LIMIT,
    }


class CreateIn(BaseModel):
    request: str = Field(default="", max_length=2000)
    project_ids: list[uuid.UUID] | None = None  # None / empty = all projects the user may report on
    person_ids: list[uuid.UUID] | None = None  # None / empty = everyone
    period_start: date
    period_end: date
    format_mode: str = Field(default="auto", pattern="^(auto|visibility|sample)$")
    format_sample: str = Field(default="", max_length=SAMPLE_LIMIT)


def _check_quota(ctx: Ctx) -> None:
    """Per-company daily limit on AI reports (counted from midnight company time)."""
    from datetime import datetime, time

    from ..services.timeutil import company_now

    tz_now = company_now(ctx.company.timezone)
    start = datetime.combine(tz_now.date(), time.min, tzinfo=tz_now.tzinfo)
    used = ctx.db.execute(select(func.count()).select_from(AiReport).where(AiReport.created_at >= start)).scalar_one()
    if used >= ctx.company.ai_daily_report_quota:
        raise ApiError(429, "quota.reports", f"Your company has reached today's limit of {ctx.company.ai_daily_report_quota} AI reports. Try again tomorrow.")


@router.post("/ai-reports", status_code=202)
def create(body: CreateIn, ctx: Ctx = Depends(ai_ctx)):
    if body.period_end < body.period_start:
        raise bad_request("invalid_range", "The period must end on or after the day it starts.")
    if (body.period_end - body.period_start).days > 400:
        raise bad_request("invalid_range", "Choose a period of at most 400 days.")
    if body.format_mode == "sample" and len(body.format_sample.strip()) < 20:
        raise bad_request("sample_required", "Paste the sample or outline of the report you want (at least a few lines)")
    allowed, unrestricted = _allowed_projects(ctx)
    wanted = [str(p) for p in (body.project_ids or [])]
    if wanted:
        known = {str(i) for i in ctx.db.execute(select(Project.id).where(Project.id.in_([uuid.UUID(w) for w in wanted]))).scalars()}
        if known != set(wanted):
            raise bad_request("invalid_project", "One or more projects do not exist")
        if not unrestricted and not set(wanted) <= set(allowed):
            raise forbidden("You can only report on projects you own")
    project_ids: list[str] | None = wanted or (None if unrestricted else allowed)
    people = [str(p) for p in (body.person_ids or [])]
    if people:
        stmt = select(User.id).where(User.id.in_([uuid.UUID(p) for p in people]), User.is_active.is_(True))
        if not unrestricted:
            stmt = stmt.where(User.id.in_(select(ProjectMember.user_id).where(ProjectMember.project_id.in_([uuid.UUID(i) for i in allowed]))))
        if {str(i) for i in ctx.db.execute(stmt).scalars()} != set(people):
            raise bad_request("invalid_person", "One or more people cannot be included in this report")
    _check_quota(ctx)
    row = AiReport(
        company_id=ctx.company_id, created_by=ctx.me.id, request=body.request.strip(), project_ids=project_ids, person_ids=people or None,
        period_start=body.period_start, period_end=body.period_end, format_mode=body.format_mode,
        format_sample=body.format_sample.strip() if body.format_mode == "sample" else "", status="planning",
    )
    ctx.db.add(row)
    ctx.db.flush()
    jobs.enqueue(ctx.db, "ai_report.plan", ctx.company_id, {"id": str(row.id)})
    ctx.db.commit()
    return {"id": str(row.id), "status": row.status}


@router.get("/ai-reports")
def list_reports(ctx: Ctx = Depends(ai_ctx)):
    stmt = select(AiReport).order_by(AiReport.created_at.desc()).limit(50)
    if not ctx.has("report.ai.draft"):
        stmt = stmt.where(AiReport.created_by == ctx.me.id)
    return {"items": [_out(ctx, r) for r in ctx.db.execute(stmt).scalars()]}


@router.get("/ai-reports/{report_id}")
def get_report(report_id: uuid.UUID, ctx: Ctx = Depends(ai_ctx)):
    return _out(ctx, _row(ctx, report_id), detail=True)


@router.delete("/ai-reports/{report_id}", status_code=204)
def delete_report(report_id: uuid.UUID, ctx: Ctx = Depends(ai_ctx)):
    ctx.db.delete(_row(ctx, report_id))
    ctx.db.commit()


# --------------------------------------------------------------------------------------------- the three steps
class NoteIn(BaseModel):
    note: str = Field(min_length=3, max_length=1000)


@router.post("/ai-reports/{report_id}/change-structure", status_code=202)
def change_structure(report_id: uuid.UUID, body: NoteIn, ctx: Ctx = Depends(ai_ctx)):
    """'Not quite': describe the change, the structure is re-planned and shown again."""
    row = _row(ctx, report_id)
    if row.status not in ("outline_ready", "failed"):
        raise conflict("not_changeable", "The structure can only be changed while it is waiting for your review")
    row.note, row.status, row.error = body.note.strip(), "planning", None
    jobs.enqueue(ctx.db, "ai_report.plan", ctx.company_id, {"id": str(row.id), "rev": uuid.uuid4().hex})
    ctx.db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/ai-reports/{report_id}/approve", status_code=202)
def approve_structure(report_id: uuid.UUID, ctx: Ctx = Depends(ai_ctx)):
    """'Looks good': the report is written. Idempotent (double click)."""
    row = _row(ctx, report_id)
    if row.status in ("generating", "ready"):
        return {"id": str(row.id), "status": row.status}
    if row.status != "outline_ready" or row.outline is None:
        raise conflict("not_ready", "The structure is not ready for review yet")
    row.status, row.error = "generating", None
    jobs.enqueue(ctx.db, "ai_report.generate", ctx.company_id, {"id": str(row.id), "rev": uuid.uuid4().hex})
    ctx.db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/ai-reports/{report_id}/rewrite", status_code=202)
def rewrite(report_id: uuid.UUID, body: NoteIn, ctx: Ctx = Depends(ai_ctx)):
    """Same structure, new wording ('shorter', 'mention the delay')."""
    row = _row(ctx, report_id)
    if row.status != "ready":
        raise conflict("not_ready", "Only a finished report can be rewritten")
    row.note, row.status, row.error = body.note.strip(), "generating", None
    jobs.enqueue(ctx.db, "ai_report.generate", ctx.company_id, {"id": str(row.id), "rev": uuid.uuid4().hex})
    ctx.db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/ai-reports/{report_id}/retry", status_code=202)
def retry(report_id: uuid.UUID, ctx: Ctx = Depends(ai_ctx)):
    row = _row(ctx, report_id)
    if row.status != "failed":
        raise conflict("not_failed", "Only a failed report can be retried")
    kind = "ai_report.generate" if row.outline is not None and row.facts is not None else "ai_report.plan"
    row.status, row.error = ("generating" if kind.endswith("generate") else "planning"), None
    jobs.enqueue(ctx.db, kind, ctx.company_id, {"id": str(row.id), "rev": uuid.uuid4().hex})
    ctx.db.commit()
    return {"id": str(row.id), "status": row.status}


class FeedbackIn(BaseModel):
    rating: str = Field(pattern="^(up|down)$")
    reason: str = Field(default="", max_length=500)


@router.post("/ai-reports/{report_id}/feedback", status_code=204)
def feedback(report_id: uuid.UUID, body: FeedbackIn, ctx: Ctx = Depends(ai_ctx)):
    """Thumbs up/down with an optional reason; one vote per person and report (changing it replaces the vote)."""
    row = _row(ctx, report_id)
    mine = ctx.db.execute(select(AiFeedback).where(AiFeedback.target_type == "report", AiFeedback.target_id == row.id, AiFeedback.created_by == ctx.me.id)).scalar_one_or_none()
    rating = 1 if body.rating == "up" else -1
    if mine is None:
        ctx.db.add(AiFeedback(company_id=ctx.company_id, target_type="report", target_id=row.id, rating=rating, reason=body.reason.strip(), created_by=ctx.me.id))
    else:
        mine.rating, mine.reason = rating, body.reason.strip()
    ctx.db.commit()


# --------------------------------------------------------------------------------------------- the result
@router.get("/ai-reports/{report_id}/preview")
def preview(report_id: uuid.UUID, ctx: Ctx = Depends(ai_ctx)):
    row = _row(ctx, report_id)
    if not row.markdown:
        raise conflict("not_ready", "The report has not been written yet")
    return {"html": markdown_to_html(row.markdown, row.title or "Report")}


@router.get("/ai-reports/{report_id}/markdown")
def markdown(report_id: uuid.UUID, ctx: Ctx = Depends(ai_ctx)):
    row = _row(ctx, report_id)
    if not row.markdown:
        raise ApiError(409, "not_ready", "The report has not been written yet")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{row.title or 'report'}-{row.period_start}").strip("-")
    return Response(row.markdown, media_type=MEDIA_MD, headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
