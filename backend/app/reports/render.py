"""One HTML template renders the on-screen report, the PDF and the shared client page."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .base import REGISTRY

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True, lstrip_blocks=True,
)


def _fmt_date(v: str | None) -> str:
    from datetime import date

    if not v:
        return ""
    try:
        return date.fromisoformat(v).strftime("%d %b %Y")
    except ValueError:
        return v


_env.filters["d"] = _fmt_date
_env.filters["paragraphs"] = lambda s: [p.strip() for p in str(s or "").split("\n") if p.strip()]


def markdown_for(
    report_key: str, figures: dict[str, Any], company_name: str, *, title: str | None = None, sections: dict[str, Any] | None = None,
    section_order: list[str] | None = None, client_name: str | None = None,
) -> str:
    """The report as Markdown (what the .md download contains and what the visibility report is rendered from)."""
    from . import mdreport

    title = title or REGISTRY[report_key].title
    if report_key == "visibility":
        return mdreport.visibility_markdown(figures, title, company_name, sections, client_name)
    return mdreport.generic_markdown(figures, title, company_name, sections, section_order, client_name)


def markdown_to_html(md: str, title: str) -> str:
    import markdown

    from . import mermaid

    body = mermaid.replace_blocks(markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"]))
    return _env.get_template("markdown_doc.html").render(title=title, body=body)


def render_report_html(
    report_key: str, figures: dict[str, Any], company_name: str, *, title: str | None = None,
    sections: dict[str, str] | None = None, section_order: list[str] | None = None, client_name: str | None = None,
) -> str:
    """Without `sections` the report's own figures template is used; with them (AI/edited narrative),
    the client template lays the text out section by section."""
    defn = REGISTRY[report_key]
    if report_key == "visibility":  # rendered from its markdown so the preview, PDF and .md can never disagree
        return markdown_to_html(markdown_for(report_key, figures, company_name, title=title, sections=sections, client_name=client_name), title or defn.title)
    ctx = {
        "title": title or defn.title, "company_name": company_name, "figures": figures, "client_name": client_name,
        "period": figures.get("period", {}),
    }
    if sections is not None:
        order = section_order or [k for k in sections if not k.startswith("_")]
        ctx["sections"] = [(name, sections.get(name, "")) for name in order]
        return _env.get_template("client.html").render(**ctx)
    return _env.get_template(defn.template).render(**ctx)
