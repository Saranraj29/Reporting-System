"""Report structures. An outline is what the requester approves before anything is written:
{"title", "heading_level" (1|2), "notes", "sections": [{"id", "title", "scope": overall|per_project, "kind": block|text,
 "block" | "brief", "style": paragraph|bullets|quote, "label"}]}. Three sources: the industry-standard structure, the Project Visibility
layout, and the requester's own sample (planned by the AI, or by keyword matching when no AI is configured)."""

import re
from typing import Any

from .blocks import CATALOG, VISUAL

STYLES = ("paragraph", "bullets", "quote")
MAX_SECTIONS = 25


def _t(title: str, scope: str, brief: str, style: str = "paragraph", label: str = "") -> dict[str, Any]:
    return {"title": title, "scope": scope, "kind": "text", "brief": brief, "style": style, "label": label}


def _b(title: str, block: str) -> dict[str, Any]:
    return {"title": title, "scope": CATALOG[block][0], "kind": "block", "block": block}


def standard_outline(request: str = "") -> dict[str, Any]:
    """Industry-standard project status report: summary first, metrics, health, per-project detail, risks, effort, outlook."""
    return validate_outline({
        "title": "Project Status Report", "heading_level": 2,
        "notes": "Standard status-report structure: executive summary, key metrics, project health, detail per project, risks, effort and outlook.",
        "sections": [
            _t("Executive summary", "overall", "2-4 sentences for a busy reader: overall progress, effort, and the single most important risk or decision."),
            _b("Key metrics", "totals_row"),
            _b("Project health", "health_pie"),
            _b("Project summary", "projects_table"),
            _b("{project}", "header_table"),
            _t("Progress", "per_project", "2-3 sentences on what moved this period and what is in the way."),
            _b("Task numbers", "kpi_row"),
            _b("Completed deliverables", "deliverables_table"),
            _b("Risks & blockers", "risks_table"),
            _t("Risks and issues", "overall", "The main risks across the projects and what should be done about them, as short bullet points.", "bullets"),
            _b("Effort by project", "effort_project_table"),
            _b("Effort by activity", "effort_activity_pie"),
            _t("Outlook and next steps", "overall", "What happens next and which decisions or help are needed, as short bullet points.", "bullets"),
        ],
    })


def visibility_outline() -> dict[str, Any]:
    """The 'Project Visibility Report' layout: per project header, sprint goal, KPI row, charts, workflow, activities, deliverables, then dashboards."""
    return validate_outline({
        "title": "Project Visibility Report", "heading_level": 1,
        "notes": "The Project Visibility Report layout: one block per project, then the combined dashboards.",
        "sections": [
            _b("📊 Project Visibility Report — {project}", "header_table"),
            _t("🎯 Sprint Goal & Objectives", "per_project", "ONE sentence: what this project set out to deliver in the period.", "quote", "Sprint Goal"),
            _b("Planned vs completed", "kpi_row"),
            _b("📈 Sprint Status Distribution", "status_pie"),
            _b("🚀 {project} Workflow", "workflow"),
            _b("Current Activities", "activities_table"),
            _b("✅ Completed Deliverables", "deliverables_table"),
            _b("📈 Work Distribution", "work_pie"),
            _b("📊 Combined Sprint Health Dashboard", "health_pie"),
            _b("📊 Summary Dashboard", "projects_table"),
            _b("📊 Team Work Distribution", "team_pie"),
        ],
    })


# ------------------------------------------------------------------------------------------- sample -> outline without an AI
_RULES: list[tuple[str, str]] = [  # first match wins
    (r"(combined|overall|portfolio|consolidated).*(health|dashboard|progress)", "health_pie"),
    (r"summary dashboard|project summary|portfolio summary|projects? overview|status summary", "projects_table"),
    (r"team (work|effort)|resource (allocation|utili)|workload", "team_pie"),
    (r"effort by project|hours by project|time by project", "effort_project_table"),
    (r"work distribution|effort (distribution|by activity)|time distribution", "work"),
    (r"status (distribution|chart)|progress distribution|sprint (dashboard|status)|status overview", "status_pie"),
    (r"workflow|process flow", "workflow"),
    (r"deliverable|accomplish|completed work|achievement", "deliverables_table"),
    (r"activit|task list|work items|current work|work in progress", "activities_table"),
    (r"risk|blocker|issue", "risks"),
    (r"upcoming|coming up|due (soon|next)", "upcoming"),
    (r"goal|objective", "goal"),
    (r"project (visibility )?report|project (details|information|profile)|reporting period", "header_table"),
    (r"kpi|key (metrics|figures)|task numbers|scorecard|metrics", "kpi"),
]
_PAIRS = {"kpi": ("kpi_row", "totals_row"), "work": ("work_pie", "effort_activity_pie"), "risks": ("risks_table", "risks_all_table"),
          "upcoming": ("upcoming_table", "upcoming_all_table")}


def _plain(title: str) -> str:
    return re.sub(r"^[\W_]+", "", title).strip() or title.strip()


def _project_template(titles: list[str]) -> str:
    """['🚀 A Workflow', '🚀 B Workflow'] -> '🚀 {project} Workflow' (what varies between the repeats is the project name)."""
    if len(set(titles)) == 1:
        return titles[0]
    parts = [t.split() for t in titles]
    pre = 0
    while all(len(x) > pre for x in parts) and len({x[pre] for x in parts}) == 1:
        pre += 1
    suf = 0
    while all(len(x) > pre + suf for x in parts) and len({x[-1 - suf] for x in parts}) == 1:
        suf += 1
    first = parts[0]
    return " ".join([*first[:pre], "{project}", *(first[len(first) - suf:] if suf else [])])


def _plain_lines(sample: str) -> list[str]:
    """A sample without markdown headings is usually a typed list of sections ("1. Summary", "- Risks", "Next steps").
    Short lines without sentence punctuation count as section titles; at least three are needed."""
    out: list[str] = []
    for raw in sample[:40000].splitlines():
        line = re.sub(r"^\s*(?:[-*•]+|\d+(?:\.\d+)*[.)]?|[A-Za-z][.)])\s+", "", raw).strip().rstrip(":").strip()
        if not line or len(line) > 70 or re.search(r"[.!?]$", line) or re.fullmatch(r"[|:\-\s]+", line) or line.startswith("|"):
            continue
        out.append(line)
    return out[:25] if len(out) >= 3 else []


def sample_outline(sample: str) -> dict[str, Any]:
    """Maps the headings of a sample report to blocks by keywords (used when no AI is configured, and as a safety net).
    Repeated headings (one block per project) become per-project sections, headings that occur once after them become overall sections.
    Anything that matches no block becomes a text section written from the facts."""
    heads = [(len(m.group(1)), m.group(2).strip()) for m in re.finditer(r"^(#{1,3})\s+(.+?)\s*$", sample[:40000], re.M)]
    if not heads:
        heads = [(2, line) for line in _plain_lines(sample)]
    if not heads:
        return standard_outline()
    level = 1 if sum(1 for lvl, _ in heads if lvl == 1) >= 3 else 2
    keep = [raw for lvl, raw in heads if lvl in ((1, 2) if level == 1 else (2,))] or [raw for _, raw in heads]
    items: list[tuple[str, str | None, str]] = []  # (key, rule, raw title)
    for raw in keep:
        plain = _plain(raw)
        rule = next((name for pat, name in _RULES if re.search(pat, plain.lower())), None)
        items.append((rule or re.split(r"\s[—–-]\s", plain.lower())[0], rule, raw))
    counts: dict[str, int] = {}
    titles: dict[str, list[str]] = {}
    for key, _, raw in items:
        counts[key] = counts.get(key, 0) + 1
        titles.setdefault(key, []).append(raw)
    repeats = any(c >= 2 for c in counts.values())
    quote_goal = bool(re.search(r">\s*\*\*[^*]*goal", sample, re.I))
    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, rule, raw in items:
        if key in seen:
            continue
        seen.add(key)
        per = counts[key] >= 2
        title = _project_template(titles[key]) if per else raw
        if rule is None and not per and re.search(r"\b(per|by|for each|each)\s+project|project[- ]wise", raw.lower()):
            per = True
            title = re.sub(r"\s*[-—–:]?\s*\b(per|by|for each|each)\s+project.*$|\s*project[- ]wise.*$", "", _plain(raw), flags=re.I).strip() or "Details"
            title += " — {project}"
        if rule is None:
            sections.append(_t(title, "per_project" if per else "overall", f"Short written “{_plain(raw)}” section based on your project data.",
                               "bullets" if re.search(r"next steps|recommend|action", raw.lower()) else "paragraph"))
        elif rule == "goal":
            sections.append(_t(title, "per_project" if (per or repeats) else "overall", "ONE sentence: what the project set out to deliver in the period.",
                               "quote" if quote_goal else "paragraph", "Sprint Goal" if quote_goal else ""))
            sections.append(_b("Task numbers", "kpi_row" if (per or repeats) else "totals_row"))
        else:
            block = rule
            if rule in _PAIRS:
                block = _PAIRS[rule][0 if (per or repeats) else 1]
            if CATALOG[block][0] == "per_project" and not per and " — " in title and "{project}" not in title:
                title = re.sub(r"\s+—\s+.*$", " — {project}", title)
            sections.append(_b(title, block))
    first_h1 = next((_plain(r) for lvl, r in heads if lvl == 1), "Project Report")
    return validate_outline({"title": first_h1 if level == 2 else "Project Report", "heading_level": level, "notes": "Built from the headings of your sample.", "sections": sections})


# ------------------------------------------------------------------------------------------- validation
def validate_outline(raw: Any) -> dict[str, Any]:
    """Normalises an outline from any source (AI output included). Raises ValueError if nothing usable is left."""
    if not isinstance(raw, dict) or not isinstance(raw.get("sections"), list):
        raise ValueError("outline has no sections")
    sections: list[dict[str, Any]] = []
    for item in raw["sections"][:MAX_SECTIONS]:
        if not isinstance(item, dict):
            continue
        title = re.sub(r"[\x00-\x1f]", " ", str(item.get("title") or "")).strip()[:120]
        if not title:
            continue
        block = str(item.get("block") or "")
        if item.get("kind") == "block" and block in CATALOG:
            sections.append({"title": title, "scope": CATALOG[block][0], "kind": "block", "block": block})
            continue
        style = item.get("style") if item.get("style") in STYLES else "paragraph"
        scope = "per_project" if item.get("scope") == "per_project" else "overall"
        brief = str(item.get("brief") or f"Short written “{title}” section based on your project data.").strip()[:300]
        sections.append({"title": title, "scope": scope, "kind": "text", "brief": brief, "style": style, "label": str(item.get("label") or "")[:40]})
    if not sections:
        raise ValueError("outline has no usable sections")
    for i, s in enumerate(sections, 1):
        s["id"] = f"s{i}"
    return {
        "title": (str(raw.get("title") or "Project Report").strip() or "Project Report")[:120],
        "heading_level": 1 if raw.get("heading_level") == 1 else 2,
        "notes": str(raw.get("notes") or "")[:300], "sections": sections,
    }


def describe(outline: dict[str, Any]) -> list[dict[str, Any]]:
    """What the requester sees in the structure preview: one line per section, grouped into 'once' and 'repeats for every project'."""
    out = []
    for s in outline["sections"]:
        if s["kind"] == "block":
            scope, label, what = CATALOG[s["block"]]
            out.append({"id": s["id"], "title": s["title"], "scope": s["scope"], "visual": VISUAL[s["block"]], "what": what})
        else:
            out.append({"id": s["id"], "title": s["title"], "scope": s["scope"], "visual": "text", "what": s["brief"]})
    return out
