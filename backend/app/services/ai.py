"""AI drafting. The model only ever sees aggregated figures for the client's own projects plus the
template's instructions; it never gets comments, daily-status text, per-person figures or other tenants' data.
Swapping providers means changing `_call_model` only."""

import json
import re
from typing import Any

from ..config import get_settings

FORBIDDEN_KEYS = {"people", "comments", "daily_status", "performance", "email", "emails"}

SYSTEM_PROMPT = """You write the narrative sections of a report that a company sends to its client.
Rules you must follow:
1. Use ONLY the numbers and facts in the FIGURES JSON. Never invent facts, dates, causes or promises.
2. If something a section needs is missing from the figures, do not guess; add a short question for the
   reviewer to the "questions" list instead.
3. Do not mention internal team member names, internal tooling or anything not present in the figures.
4. Follow the tone instructions and the requested format exactly.
5. Reply with a single JSON object and nothing else:
   {"sections": {"<section name>": "<text>", ...}, "questions": ["...", ...]}
   Use exactly the section names provided. Separate paragraphs inside a section with a blank line."""

FORMAT_HINT = {
    "narrative": "Write flowing prose paragraphs.",
    "bullet_summary": "Write short bullet points, one per line, each starting with '- '.",
    "table_commentary": "Write one or two sentences of commentary per section that refer to the figures; the tables are added separately.",
}


def sanitize_figures(obj: Any) -> Any:
    """Defence in depth: strip anything personal or internal before the model call."""
    if isinstance(obj, dict):
        return {k: sanitize_figures(v) for k, v in obj.items() if k not in FORBIDDEN_KEYS}
    if isinstance(obj, list):
        return [sanitize_figures(v) for v in obj]
    return obj


def build_user_prompt(figures: dict, template: dict, note: str | None, previous: dict | None) -> str:
    parts = [
        f"Report: {template.get('name', 'Client report')}",
        f"Format: {template.get('format', 'narrative')} — {FORMAT_HINT.get(template.get('format', 'narrative'), '')}",
        f"Tone instructions: {template.get('tone_instructions') or 'Professional and concise.'}",
        "Sections (in order): " + json.dumps(template.get("sections", [])),
        "FIGURES:\n" + json.dumps(sanitize_figures(figures), indent=1, default=str),
    ]
    if previous and note:
        prev = {k: v for k, v in previous.items() if not k.startswith("_")}
        parts.append("PREVIOUS DRAFT:\n" + json.dumps(prev, indent=1))
    if note:
        parts.append(f"REVIEWER NOTE (apply this to the redraft): {note}")
    return "\n\n".join(parts)


def _call_model(system: str, user: str) -> str:
    import anthropic

    s = get_settings()
    client = anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=1, timeout=60)
    msg = client.messages.create(
        model=s.anthropic_model, max_tokens=2500, system=system, messages=[{"role": "user", "content": user}]
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def parse_model_output(raw: str, sections: list[str]) -> dict[str, Any]:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError("model returned no JSON")
    data = json.loads(m.group(0))
    got = data.get("sections", {})
    if not isinstance(got, dict):
        raise ValueError("model JSON has no sections object")
    out: dict[str, Any] = {name: str(got.get(name, "")).strip() for name in sections}
    questions = [str(q) for q in data.get("questions", []) if q]
    missing = [name for name, text_ in out.items() if not text_]
    questions += [f"No text was produced for “{n}”; please write it." for n in missing]
    if questions:
        out["_questions"] = questions
    return out


def figures_only_text(figures: dict, sections: list[str]) -> dict[str, Any]:
    """Deterministic draft built straight from the figures; used when no AI provider is configured
    or the reviewer asks to send the update without narrative."""
    t = figures.get("totals", {})
    projects = figures.get("projects", [])
    done = figures.get("completed_tasks", [])
    blockers, overdue, upcoming = figures.get("blockers", []), figures.get("overdue", []), figures.get("upcoming", [])
    p = figures.get("period", {})
    out: dict[str, Any] = {}
    for name in sections:
        key = name.lower()
        if "summary" in key or "overview" in key:
            out[name] = (
                f"Between {p.get('start')} and {p.get('end')} the team logged {t.get('hours', 0)} hours and completed "
                f"{t.get('tasks_completed', 0)} task(s). {t.get('tasks_open', 0)} task(s) remain open."
            )
        elif "complete" in key or "work" in key or "deliver" in key:
            out[name] = "\n".join(f"- {d['title']} ({d['project']})" for d in done) or "No tasks were completed in this period."
        elif "hour" in key or "effort" in key or "time" in key:
            out[name] = "\n".join(f"- {r['project']}: {r['hours']} h" for r in projects) or "No hours were logged in this period."
        elif "risk" in key or "block" in key or "issue" in key:
            lines = [f"- {b['title']} is blocked ({b['project']})" for b in blockers]
            lines += [f"- {o['title']} is {o['days_late']} day(s) overdue ({o['project']})" for o in overdue]
            out[name] = "\n".join(lines) or "No blockers or overdue work."
        elif "next" in key or "upcoming" in key or "plan" in key:
            out[name] = "\n".join(f"- {u['title']} — due {u['due_date']} ({u['project']})" for u in upcoming) or "No dated work is scheduled yet."
        else:
            out[name] = ""
    empty = [n for n, v in out.items() if not v]
    if empty:
        out["_questions"] = [f"“{n}” has no figures-based content; please write it." for n in empty]
    return out


def draft_report_text(
    figures: dict, template: dict, note: str | None = None, previous: dict | None = None, figures_only: bool = False
) -> tuple[dict[str, Any], str]:
    """Returns (text per section, provider). Raises if the provider is configured but the call fails
    (the worker retries 3 times, then marks the run failed)."""
    sections: list[str] = list(template.get("sections", []))
    if figures_only or not get_settings().anthropic_api_key:
        return figures_only_text(figures, sections), "figures_only"
    raw = _call_model(SYSTEM_PROMPT, build_user_prompt(figures, template, note, previous))
    return parse_model_output(raw, sections), "anthropic"
