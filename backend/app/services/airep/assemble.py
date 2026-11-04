"""Outline + facts + narrative -> Markdown. Per-project sections are repeated for every project (like the sample reports), overall
sections appear once; numbers come from the blocks, text from the narrative."""

import re
from typing import Any

from ...reports.mdreport import esc, nice_period
from .blocks import OVERALL, PER_PROJECT


def _clean_ai(text: str) -> str:
    """AI text may use markdown, never raw HTML or fenced blocks (those are reserved for our charts)."""
    lines = [ln for ln in str(text).replace("\r", "").split("\n") if not ln.strip().startswith("```")]
    return "\n".join(lines).replace("<", "&lt;").strip()


def _text_lines(sec: dict[str, Any], text: str) -> list[str]:
    body = _clean_ai(text)
    if not body:
        return ["_Nothing to report._", ""]
    style = sec.get("style", "paragraph")
    if style == "quote":
        label = sec.get("label") or re.sub(r"^[\W_]+", "", sec["title"]).strip()
        return [f"> **{esc(label)}:** {' '.join(body.split())}", ""]
    if style == "bullets":
        items = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", ln).strip() for ln in body.split("\n") if ln.strip()]
        return [*[f"- {i}" for i in items], ""]
    out: list[str] = []
    for para in (p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()):
        prev_item = False
        for ln in para.split("\n"):
            is_item = bool(re.match(r"\s*[-*•]\s+", ln))
            if is_item and not prev_item and out and out[-1] != "":
                out.append("")  # markdown needs a blank line before a list
            out.append(re.sub(r"^\s*[*•]\s+", "- ", ln) if is_item else ln)
            prev_item = is_item
        out.append("")
    return out


def _heading(level: int, title: str, project: str | None, period: str) -> str:
    t = " ".join(title.replace("{project}", project or "").replace("{period}", period).replace("<", "&lt;").replace("|", "\\|").split())
    return f"{'#' * level} {t}"


def assemble(outline: dict[str, Any], facts: dict[str, Any], narrative: dict[str, Any], company: str = "") -> str:
    level = outline["heading_level"]
    period = nice_period(facts["period"])
    secs = outline["sections"]
    projects = facts["projects"]
    first_pp = next((i for i, s in enumerate(secs) if s["scope"] == "per_project"), None)
    front = [s for i, s in enumerate(secs) if s["scope"] == "overall" and (first_pp is None or i < first_pp)]
    group = [s for s in secs if s["scope"] == "per_project"]
    back = [s for i, s in enumerate(secs) if s["scope"] == "overall" and first_pp is not None and i > first_pp]

    # level-2 reports whose first per-project section is the project's own heading nest the rest of that group one level deeper
    nest = level == 2 and len(group) > 1 and "{project}" in group[0]["title"]

    def render(sec: dict[str, Any], p: dict[str, Any] | None) -> list[str]:
        deeper = nest and p is not None and sec is not group[0]
        head = _heading(level + 1 if deeper else level, sec["title"], p["name"] if p else None, period)
        if sec["kind"] == "text":
            key = f"{sec['id']}::{p['name']}" if p else sec["id"]
            return [head, "", *_text_lines(sec, narrative.get(key, ""))]
        if p is not None:
            return [head, "", *PER_PROJECT[sec["block"]](p, facts, narrative)]
        return [head, "", *OVERALL[sec["block"]](facts, narrative)]

    md: list[str] = []
    if level == 2:
        md += [f"# {esc(outline['title'])}", "", f"_{esc(company)} · {period} · {len(projects)} project{'s' if len(projects) != 1 else ''}"
               f"{' · work by ' + esc(', '.join(facts['people_filter'])) if facts.get('people_filter') else ''}_", ""]
    blocks: list[list[str]] = [render(s, None) for s in front]
    if group:
        for p in projects:
            blocks.append([line for s in group for line in render(s, p)])
    blocks += [render(s, None) for s in back]
    if not projects:
        blocks = [[f"No project activity between {period}.", ""]]
    for i, b in enumerate(blocks):
        md += b
        if level == 1 and i < len(blocks) - 1:
            md += ["---", ""]
    if facts.get("no_activity"):
        md += [f"_No activity in this period for: {esc(', '.join(facts['no_activity']))}._", ""]
    return "\n".join(md).rstrip() + "\n"
