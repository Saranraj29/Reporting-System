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


def render_report_html(
    report_key: str, figures: dict[str, Any], company_name: str, *, title: str | None = None,
    sections: dict[str, str] | None = None, section_order: list[str] | None = None, client_name: str | None = None,
) -> str:
    """Without `sections` the report's own figures template is used; with them (AI/edited narrative),
    the client template lays the text out section by section."""
    defn = REGISTRY[report_key]
    ctx = {
        "title": title or defn.title, "company_name": company_name, "figures": figures, "client_name": client_name,
        "period": figures.get("period", {}),
    }
    if sections is not None:
        order = section_order or [k for k in sections if not k.startswith("_")]
        ctx["sections"] = [(name, sections.get(name, "")) for name in order]
        return _env.get_template("client.html").render(**ctx)
    return _env.get_template(defn.template).render(**ctx)
