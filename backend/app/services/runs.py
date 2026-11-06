"""Report-run logic shared by the API and the worker: figures, rendering, files."""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..models import Client, Company, ReportRun, ReportTemplate
from ..reports import REGISTRY
from ..reports.base import ReportContext, month_bounds, week_start
from ..reports.render import markdown_for, render_report_html
from . import exporters, storage
from .timeutil import company_today


def template_snapshot(t: ReportTemplate) -> dict[str, Any]:
    return {
        "id": str(t.id), "name": t.name, "audience": t.audience, "base_report": t.base_report, "format": t.format,
        "sections": list(t.sections), "tone_instructions": t.tone_instructions,
        "client_id": str(t.client_id) if t.client_id else None,
    }


def previous_full_period(base_report: str, today: date) -> tuple[date, date]:
    """Scheduled and 'Generate' runs cover the last complete week / month."""
    if base_report == "monthly":
        first_this, _ = month_bounds(today)
        return month_bounds(first_this - timedelta(days=1))
    start = week_start(today) - timedelta(days=7)
    return start, start + timedelta(days=6)


def _uuid(v: Any) -> uuid.UUID | None:
    return uuid.UUID(str(v)) if v else None


def run_context(db: Session, run: ReportRun, company: Company) -> ReportContext:
    tpl = run.params.get("template")
    client_audience = bool(tpl and tpl["audience"] == "client")
    return ReportContext(
        db=db, start=run.period_start, end=run.period_end, today=company_today(company.timezone),
        scope_user_ids=[uuid.UUID(u) for u in run.scope_user_ids] if run.scope_user_ids is not None else None,
        project_id=_uuid(run.params.get("project")), user_id=_uuid(run.params.get("user")), team_id=_uuid(run.params.get("team")),
        client_id=_uuid(tpl["client_id"]) if tpl else None,
        include_people=not client_audience,
    )


def compute_figures(db: Session, run: ReportRun, company: Company) -> dict[str, Any]:
    figures = REGISTRY[run.report_key].query(run_context(db, run, company))
    return figures


def run_title(run: ReportRun) -> str:
    tpl = run.params.get("template")
    return tpl["name"] if tpl else REGISTRY[run.report_key].title


def client_name_for(db: Session, run: ReportRun) -> str | None:
    tpl = run.params.get("template")
    if tpl and tpl.get("client_id"):
        c = db.get(Client, uuid.UUID(tpl["client_id"]))
        return c.name if c else None
    return None


def run_sections(run: ReportRun) -> list[str]:
    """Section names of a run: dynamic ones stored by the drafting step (visibility report: per project), else the template's."""
    tpl = run.params.get("template")
    return list(run.params.get("sections") or (tpl["sections"] if tpl else []))


def _kwargs(db: Session, run: ReportRun) -> dict:
    tpl = run.params.get("template")
    return dict(
        title=run_title(run), sections=run.ai_text if (tpl and run.ai_text is not None) else None,
        section_order=run_sections(run) if tpl else None, client_name=client_name_for(db, run),
    )


def render_run_html(db: Session, run: ReportRun, company: Company) -> str:
    return render_report_html(run.report_key, run.figures or {}, company.name, **_kwargs(db, run))


def render_run_markdown(db: Session, run: ReportRun, company: Company) -> str:
    return markdown_for(run.report_key, run.figures or {}, company.name, **_kwargs(db, run))


def build_files(db: Session, run: ReportRun, company: Company, formats: list[str]) -> None:
    html = render_run_html(db, run, company)
    sections = run.ai_text if run.params.get("template") else None
    base = f"{company.id}/{run.id}/report"
    for fmt in formats:
        if fmt == "md":
            data = render_run_markdown(db, run, company).encode()
        elif fmt == "pdf":
            data = exporters.to_pdf(html)
        elif fmt == "xlsx":
            data = exporters.to_xlsx(run_title(run), run.figures or {}, sections)
        elif fmt == "docx":
            data = exporters.to_docx(run_title(run), company.name, run.figures or {}, sections)
        else:
            raise ValueError(f"unsupported format {fmt}")
        setattr(run, f"file_url_{fmt}", storage.put(f"{base}.{fmt}", data))
