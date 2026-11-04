"""Files of an AI report: .md (the report itself), .pdf (the same markdown drawn as HTML with real charts), .docx (converted from the
markdown), .xlsx (the numbers behind the report)."""

import html
import io
import re
from typing import Any

from .. import exporters, storage


def _runs(par, text: str) -> None:
    """**bold** and _italic_ inside a line."""
    for piece in re.split(r"(\*\*[^*]+\*\*|_[^_]+_)", text):
        if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            par.add_run(piece[2:-2]).bold = True
        elif piece.startswith("_") and piece.endswith("_") and len(piece) > 2:
            par.add_run(piece[1:-1]).italic = True
        elif piece:
            par.add_run(piece)


def _plain(s: str) -> str:
    return html.unescape(s.replace("\\|", "|")).strip()


def markdown_to_docx(md: str) -> bytes:
    from docx import Document

    doc = Document()
    lines = md.replace("\r", "").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            body, i = [], i + 1
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            src = "\n".join(body)
            if src.strip().startswith("pie"):
                rows = re.findall(r'^\s*"(.+?)"\s*:\s*([0-9.]+)\s*$', src, re.M)
                if rows:
                    t = doc.add_table(rows=1, cols=2)
                    t.style = "Light Grid Accent 1"
                    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Item", "Value"
                    for k, v in rows:
                        c = t.add_row().cells
                        c[0].text, c[1].text = k, v
            elif src.strip().startswith("flowchart"):
                stages = re.findall(r"\[([^\]]*)\]", src)
                if stages:
                    doc.add_paragraph(" → ".join(dict.fromkeys(stages)))
            continue
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [_plain(c) for c in re.split(r"(?<!\\)\|", lines[i].strip().strip("|"))]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c) or not any(cells):  # drop the |---|---| separator row
                    rows.append(cells)
                i += 1
            rows = [r for r in rows if any(r)]
            if rows:
                t = doc.add_table(rows=0, cols=max(len(r) for r in rows))
                t.style = "Light Grid Accent 1"
                for r in rows:
                    cells = t.add_row().cells
                    for j, c in enumerate(r):
                        cells[j].text = re.sub(r"\*\*([^*]+)\*\*", r"\1", c)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            doc.add_heading(_plain(m.group(2)), min(len(m.group(1)), 4) if len(m.group(1)) > 1 else 1)
        elif ln.startswith(">"):
            _runs(doc.add_paragraph(style="Intense Quote"), _plain(ln.lstrip("> ")))
        elif re.match(r"^\s*[-*]\s+", ln):
            _runs(doc.add_paragraph(style="List Bullet"), _plain(re.sub(r"^\s*[-*]\s+", "", ln)))
        elif re.match(r"^\s*\d+[.)]\s+", ln):
            _runs(doc.add_paragraph(style="List Number"), _plain(re.sub(r"^\s*\d+[.)]\s+", "", ln)))
        elif ln.strip() and not ln.startswith("---") and not ln.startswith("<!--"):
            _runs(doc.add_paragraph(), _plain(ln))
        i += 1
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_files(db, row, company_name: str, md: str, facts: dict[str, Any], title: str) -> dict[str, str | None]:
    """Stores the four files and returns their storage keys. The PDF needs a browser engine; if it fails the other files are still delivered."""
    from ...reports.render import markdown_to_html

    base = f"{row.company_id}/ai/{row.id}/report"
    keys: dict[str, str | None] = {"md": storage.put(f"{base}.md", md.encode()), "pdf": None, "docx": None, "xlsx": None}
    keys["docx"] = storage.put(f"{base}.docx", markdown_to_docx(md))
    keys["xlsx"] = storage.put(f"{base}.xlsx", exporters.to_xlsx(title, {k: v for k, v in facts.items() if k != "company"}, None))
    try:
        keys["pdf"] = storage.put(f"{base}.pdf", exporters.to_pdf(markdown_to_html(md, title)))
    except Exception:  # noqa: BLE001 - no browser engine on this machine
        keys["pdf"] = None
    return keys

