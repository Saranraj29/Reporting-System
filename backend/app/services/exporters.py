"""PDF (Playwright), Excel (openpyxl) and Word (python-docx) renderers. All are generic over `figures`,
so a new base report needs no exporter change."""

import io
from typing import Any

from ..config import get_settings


def to_pdf(html: str) -> bytes:
    from playwright.sync_api import sync_playwright

    s = get_settings()
    with sync_playwright() as pw:
        kwargs: dict[str, Any] = {"args": ["--no-sandbox"]}
        if s.chromium_path:
            kwargs["executable_path"] = s.chromium_path
        browser = pw.chromium.launch(**kwargs)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            return page.pdf(format="A4", print_background=True, margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
        finally:
            browser.close()


def _tables(figures: dict[str, Any]) -> list[tuple[str, list[dict]]]:
    return [(k, v) for k, v in figures.items() if isinstance(v, list) and v and all(isinstance(r, dict) for r in v)]


def _label(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _cell(v: Any) -> Any:
    """openpyxl only takes scalars: lists / dicts (e.g. a project's activities) become readable text."""
    if isinstance(v, list):
        return "; ".join(str(x) if not isinstance(x, dict) else ", ".join(str(y) for y in x.values()) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {x}" for k, x in v.items())
    return v


def to_xlsx(title: str, figures: dict[str, Any], sections: dict[str, str] | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    bold, head = Font(bold=True), PatternFill("solid", fgColor="E8EEF9")
    ws["A1"], ws["A1"].font = title, Font(bold=True, size=14)
    p = figures.get("period", {})
    ws["A2"] = f"{p.get('start', '')} – {p.get('end', '')}"
    row = 4
    for key, value in figures.items():
        if isinstance(value, dict) and key != "period":
            ws.cell(row, 1, _label(key)).font = bold
            row += 1
            for k, v in value.items():
                if isinstance(v, dict):
                    continue
                ws.cell(row, 1, _label(k))
                ws.cell(row, 2, v)
                row += 1
            row += 1
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 18
    if sections:
        ns = wb.create_sheet("Narrative")
        r = 1
        for name, body in sections.items():
            if name.startswith("_"):
                continue
            ns.cell(r, 1, name).font = bold
            c = ns.cell(r + 1, 1, body)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            r += 3
        ns.column_dimensions["A"].width = 110
    for key, rows in _tables(figures):
        sh = wb.create_sheet(_label(key)[:31])
        cols = list(rows[0].keys())
        for i, col in enumerate(cols, 1):
            c = sh.cell(1, i, _label(col))
            c.font, c.fill = bold, head
        for r_i, r in enumerate(rows, 2):
            for c_i, col in enumerate(cols, 1):
                sh.cell(r_i, c_i, _cell(r.get(col)))
        for i, col in enumerate(cols, 1):
            width = max(len(_label(col)), *(len(str(_cell(r.get(col, "")))) for r in rows)) + 2
            sh.column_dimensions[get_column_letter(i)].width = min(width, 60)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_docx(title: str, company_name: str, figures: dict[str, Any], sections: dict[str, str] | None = None) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading(title, 0)
    p = figures.get("period", {})
    doc.add_paragraph(f"{company_name} · {p.get('start', '')} – {p.get('end', '')}")
    totals = figures.get("totals")
    if isinstance(totals, dict):
        t = doc.add_table(rows=0, cols=2)
        t.style = "Light Grid Accent 1"
        for k, v in totals.items():
            cells = t.add_row().cells
            cells[0].text, cells[1].text = _label(k), str(v)
    if sections:
        for name, body in sections.items():
            if name.startswith("_"):
                continue
            doc.add_heading(name, 1)
            for para in [x.strip() for x in str(body).split("\n") if x.strip()]:
                if para.startswith("- "):
                    doc.add_paragraph(para[2:], style="List Bullet")
                else:
                    doc.add_paragraph(para)
    else:
        for key, rows in _tables(figures):
            doc.add_heading(_label(key), 1)
            cols = list(rows[0].keys())
            table = doc.add_table(rows=1, cols=len(cols))
            table.style = "Light Grid Accent 1"
            for i, col in enumerate(cols):
                table.rows[0].cells[i].text = _label(col)
            for r in rows:
                cells = table.add_row().cells
                for i, col in enumerate(cols):
                    cells[i].text = "" if r.get(col) is None else str(_cell(r.get(col)))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
