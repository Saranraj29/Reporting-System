"""Markdown output of a report. The visibility report follows the "Project Visibility Report" layout (header table, sprint goal
and KPI row, mermaid charts, workflow, activities, deliverables, work distribution, then the combined dashboards); every other
report gets a generic markdown rendering of its figures. All dynamic text is escaped: markdown is also turned into HTML for the
on-screen report, the PDF and the shared page, so nothing in a task title or AI text may become markup."""

import re
from datetime import date
from typing import Any

STATUS_LABEL = {"completed": "🟢 Completed", "in_progress": "🟡 In Progress"}
ACTIVITY_STATUS = {"done": "✅ Completed", "todo": "📅 Pending"}  # anything else is work in flight
SECTION_PREFIXES = ("Sprint goal", "Workflow", "Key achievement")
SEP = " — "  # key of an AI section: "Sprint goal — <project>"


def key(prefix: str, project: str) -> str:
    return f"{prefix}{SEP}{project}"


def esc(s: Any) -> str:
    """Neutralise anything that could become markup or break a table cell."""
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace("\r", "").replace("\n", " ").replace("|", "\\|").strip()


def label(s: Any, limit: int = 60) -> str:
    """Text for mermaid labels: no quotes or bracket characters, bounded length."""
    t = re.sub(r"[\"'\[\](){}<>|#;`]", " ", str(s or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return (t[: limit - 1] + "…") if len(t) > limit else t


def pie_label(s: Any, limit: int = 50) -> str:
    """Pie labels sit inside quotes, so parentheses are fine ("Schedulator (88%)"); only quotes and markup are removed."""
    t = re.sub(r"[\"<>`|]", " ", str(s or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return (t[: limit - 1] + "…") if len(t) > limit else t


def nice_period(period: dict[str, str]) -> str:
    a, b = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    return f"{a:%d %b} – {b:%d %b %Y}" if a.year == b.year else f"{a:%d %b %Y} – {b:%d %b %Y}"


# ------------------------------------------------------------------------------------------- deterministic fallbacks
def fallback_goal(p: dict[str, Any]) -> str:
    names = [a["title"] for a in p["activities"][:3]]
    focus = "; ".join(names)
    return f"Deliver the {p['planned']} planned task{'s' if p['planned'] != 1 else ''} for {p['name']}" + (f" — {focus}." if focus else ".")


def fallback_workflow(p: dict[str, Any]) -> list[str]:
    types = [d["label"] for d in p["work_distribution"]]
    stages = types[:4] if len(types) >= 2 else ["Planning", "Development", "Review", "Delivery"]
    return stages


def fallback_achievement(p: dict[str, Any]) -> str:
    if p["deliverables"]:
        return f"{p['completed']} of {p['planned']} tasks completed; latest: {p['deliverables'][-1]}"
    return f"{p['in_progress']} task{'s' if p['in_progress'] != 1 else ''} in progress"


def narrative(p: dict[str, Any], ai: dict[str, Any] | None) -> tuple[str, list[str], str]:
    """(sprint goal, workflow stages, key achievement): the reviewed AI text when present, otherwise the figures-based fallback."""
    ai = ai or {}
    goal = str(ai.get(key("Sprint goal", p["name"])) or "").strip() or fallback_goal(p)
    wf_text = str(ai.get(key("Workflow", p["name"])) or "").strip()
    stages = [s.strip() for s in re.split(r"\s*(?:→|->|\n)\s*", wf_text) if s.strip()] or fallback_workflow(p)
    achievement = str(ai.get(key("Key achievement", p["name"])) or "").strip() or fallback_achievement(p)
    return goal, stages[:7], achievement


# ------------------------------------------------------------------------------------------- visibility layout
def _pie(title: str, items: list[tuple[str, float]]) -> list[str]:
    rows = [(pie_label(k), v) for k, v in items if v > 0]
    if not rows:
        return []
    return ["```mermaid", f"pie title {pie_label(title)}", *[f'    "{k}" : {v:g}' for k, v in rows], "```", ""]


def _flow(stages: list[str]) -> list[str]:
    ids = "ABCDEFGHIJ"
    out = ["```mermaid", "flowchart LR", "", f"{ids[0]}[{label(stages[0])}]"]
    if len(stages) > 1:
        out.append(f"-->{ids[1]}[{label(stages[1])}]")
    for i in range(2, len(stages)):
        out += ["", f"{ids[i - 1]}-->{ids[i]}[{label(stages[i])}]"]
    return [*out, "```", ""]


def _project_block(p: dict[str, Any], period: str, ai: dict[str, Any] | None, internal: bool) -> list[str]:
    goal, stages, _ = narrative(p, ai)
    owner_row = [f"| **Owner** | {esc(', '.join(p.get('owners') or []) or '—')} |"] if internal else []
    md = [
        f"# 📊 Project Visibility Report — {esc(p['name'])}", "",
        "| | |", "|---|---|", f"| **Reporting Period** | {period} |", f"| **Project** | {esc(p['name'])} |", *owner_row,
        f"| **Status** | {STATUS_LABEL[p['status']]} |", "", "---", "",
        "# 🎯 Sprint Goal & Objectives", "", f"> **Sprint Goal:** {esc(goal)}", "",
        "| 🎯 Planned Tasks | ✅ Completed | 🚧 In Progress | 📅 Pending | 📊 Sprint Progress |", "|:---:|:---:|:---:|:---:|:---:|",
        f"| **{p['planned']}** | **{p['completed']}** | **{p['in_progress']}** | **{p['pending']}** | **{p['progress']}%** |", "",
        "---", "", "# 📈 Sprint Dashboard", "", "## Sprint Status Distribution", "",
        *_pie("Sprint Progress Distribution", [("Completed", p["completed"]), ("In Progress", p["in_progress"]), ("Pending", p["pending"])]),
        "---", "", f"# 🚀 {esc(p['name'])} Workflow", "", *_flow(stages), "---", "",
        "## Current Activities", "", "| Activity | Status |", "|---|---|",
        *[f"| {esc(a['title'])} | {ACTIVITY_STATUS.get(a['status'], '🚧 In Progress')} |" for a in p["activities"]],
        "", "---", "", "# ✅ Completed Deliverables", "",
    ]
    if p["deliverables"]:
        md += ["| # | Deliverable | Status |", "|---|---|:---:|", *[f"| {i} | {esc(d)} | ✅ |" for i, d in enumerate(p["deliverables"], 1)], ""]
    else:
        md += ["_No deliverables were completed in this period._", ""]
    md += ["---", "", "# 📈 Work Distribution", "", *_pie("Work Distribution", [(d["label"], d["pct"]) for d in p["work_distribution"]]), "---", ""]
    return md


def visibility_markdown(figures: dict[str, Any], title: str, company: str, ai: dict[str, Any] | None = None, client_name: str | None = None) -> str:
    projects = figures["projects"]
    internal = any("owners" in p for p in projects) or "team_distribution" in figures
    period = nice_period(figures["period"])
    head = [f"<!-- {esc(company)} · {esc(title)}{(' · ' + esc(client_name)) if client_name else ''} · {period} -->", ""]
    if not projects:
        return "\n".join([*head, f"# 📊 {esc(title)}", "", f"No project activity between {period}.", ""])
    md = head
    for p in projects:
        md += _project_block(p, period, ai, internal)
    if len(projects) > 1:
        md += ["# 📊 Combined Sprint Health Dashboard", "", *_pie(f"Overall Sprint Health ({period})", [(f"{p['name']} ({p['progress']}%)", p["progress"]) for p in projects]), "---", ""]
        cols = ["Project", *(["Owner"] if internal else []), "Progress", "Status", "Key Achievement"]
        md += ["# 📊 Summary Dashboard", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for p in projects:
            cells = [esc(p["name"]), *([esc(", ".join(p.get("owners") or []) or "—")] if internal else []), f"{p['progress']}%",
                     STATUS_LABEL[p["status"]].split()[0], esc(narrative(p, ai)[2])]
            md.append("| " + " | ".join(cells) + " |")
        md += ["", "---", ""]
    if internal and figures.get("team_distribution"):
        md += ["# 📊 Team Work Distribution", "", *_pie(f"Team Work Distribution ({period})", [(d["label"], d["pct"]) for d in figures["team_distribution"]])]
    while md and md[-1] in ("", "---"):
        md.pop()
    return "\n".join(md) + "\n"


# ------------------------------------------------------------------------------------------- generic markdown
def _cell(v: Any) -> str:
    if isinstance(v, list):
        return esc("; ".join(str(x) if not isinstance(x, dict) else ", ".join(str(y) for y in x.values()) for x in v))
    if isinstance(v, dict):
        return esc("; ".join(f"{k}: {x}" for k, x in v.items()))
    return esc("" if v is None else v)


def _human(k: str) -> str:
    return k.replace("_", " ").capitalize()


def generic_markdown(figures: dict[str, Any], title: str, company: str, sections: dict[str, Any] | None = None,
                     order: list[str] | None = None, client_name: str | None = None) -> str:
    period = nice_period(figures["period"]) if figures.get("period") else ""
    md = [f"# {esc(title)}", "", "| | |", "|---|---|", f"| **Organisation** | {esc(company)} |"]
    if client_name:
        md.append(f"| **Prepared for** | {esc(client_name)} |")
    if period:
        md.append(f"| **Reporting Period** | {period} |")
    md += ["", "---", ""]
    totals = figures.get("totals") or figures.get("check_in_totals")
    if isinstance(totals, dict):
        scalars = [(k, v) for k, v in totals.items() if not isinstance(v, (dict, list))]
        if scalars:
            md += ["## Key figures", "", "| " + " | ".join(_human(k) for k, _ in scalars) + " |", "|" + ":---:|" * len(scalars),
                   "| " + " | ".join(f"**{_cell(v)}**" for _, v in scalars) + " |", ""]
    if sections is not None:
        for name in order or [k for k in sections if not k.startswith("_")]:
            md += [f"## {esc(name)}", "", *[f"{ln}" for ln in str(sections.get(name, "")).replace("<", "&lt;").split("\n")], ""]
    else:
        for k, v in figures.items():
            if isinstance(v, list) and v and all(isinstance(r, dict) for r in v):
                cols = list(v[0].keys())
                md += [f"## {_human(k)}", "", "| " + " | ".join(_human(c) for c in cols) + " |", "|" + "---|" * len(cols),
                       *["| " + " | ".join(_cell(r.get(c)) for c in cols) + " |" for r in v], ""]
    return "\n".join(md).rstrip() + "\n"
