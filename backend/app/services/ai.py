"""AI drafting. The model only ever sees aggregated figures for the client's own projects plus the
template's instructions; it never gets comments, daily-status text, per-person figures or other tenants' data.
Swapping providers means changing `_call_model` only."""

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import get_settings

FORBIDDEN_KEYS = {
    "people", "comments", "daily_status", "performance", "email", "emails", "check_in_totals", "check_ins", "check_in_entries",
    "owners", "team_distribution",
}

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


# ----------------------------------------------------------------------------- providers
PROVIDERS = ("anthropic", "openai", "gemini")


@dataclass(frozen=True)
class LLMConfig:
    provider: str  # anthropic | openai | gemini
    model: str
    api_key: str
    base_url: str | None = None


def _platform_key_model(provider: str) -> tuple[str | None, str]:
    s = get_settings()
    return {
        "anthropic": (s.anthropic_api_key, s.anthropic_model),
        "openai": (s.openai_api_key, s.openai_model),
        "gemini": (s.gemini_api_key, s.gemini_model),
    }[provider]


def resolve_config() -> LLMConfig | None:
    """Which LLM to use. Platform configuration only (environment): AI_PROVIDER = auto | anthropic | openai | gemini | none;
    `auto` picks the first provider that has an API key. None means "no AI": drafts are built from the figures only."""
    s = get_settings()
    provider = s.ai_provider or "auto"
    if provider == "none":
        return None
    if provider == "auto":
        provider = next((p for p in PROVIDERS if _platform_key_model(p)[0]), "")
    if provider not in PROVIDERS:
        return None
    key, model = _platform_key_model(provider)
    if not key:
        return None
    return LLMConfig(provider, model, key, s.openai_base_url if provider == "openai" else None)


def _http_error(resp: "httpx.Response", cfg: LLMConfig) -> RuntimeError:
    body = resp.text[:300].replace(cfg.api_key, "***")
    return RuntimeError(f"{cfg.provider} API returned {resp.status_code}: {body}")


def _call_anthropic(system: str, user: str, cfg: LLMConfig) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=cfg.api_key, max_retries=1, timeout=60)
    msg = client.messages.create(model=cfg.model, max_tokens=2500, system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _call_openai(system: str, user: str, cfg: LLMConfig) -> str:
    resp = httpx.post(
        f"{(cfg.base_url or 'https://api.openai.com/v1').rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {cfg.api_key}"},
        json={
            "model": cfg.model, "temperature": 0.3, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=60,
    )
    if resp.status_code >= 400:
        raise _http_error(resp, cfg)
    return resp.json()["choices"][0]["message"]["content"] or ""


def _call_gemini(system: str, user: str, cfg: LLMConfig) -> str:
    resp = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.model}:generateContent",
        headers={"x-goog-api-key": cfg.api_key},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
        },
        timeout=60,
    )
    if resp.status_code >= 400:
        raise _http_error(resp, cfg)
    parts = resp.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


_CALLERS = {"anthropic": _call_anthropic, "openai": _call_openai, "gemini": _call_gemini}


def _call_model(system: str, user: str, cfg: LLMConfig) -> str:
    """The only provider-specific code path: one prompt in, text out. Add a provider = add a function above."""
    return _CALLERS[cfg.provider](system, user, cfg)


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


VIS_SYSTEM = """You write the narrative sentences of a "Project Visibility Report" for a company. All numbers, charts and tables are
produced by the system, you only write three short pieces of text per project.
Rules you must follow:
1. Use ONLY the facts in the PROJECTS JSON (task titles, statuses, counts, effort split). Never invent facts, dates, causes or promises.
2. Never mention people: no names, owners or team members.
3. For each project return:
   - "sprint_goal": ONE sentence stating what the project set out to deliver in this period, based on its tasks.
   - "workflow": 3 to 6 SHORT stage names (2-4 words each) in the order the work flows, derived from the task titles and activity types.
   - "key_achievement": ONE short line with the most notable result (a completed deliverable or the main task in flight).
4. If something cannot be said from the data, put a short question for the reviewer in "questions" instead of guessing.
5. Reply with a single JSON object and nothing else:
   {"projects": {"<exact project name>": {"sprint_goal": "...", "workflow": ["...", "..."], "key_achievement": "..."}}, "questions": []}"""


def visibility_section_keys(figures: dict) -> list[str]:
    from ..reports import mdreport

    return [mdreport.key(prefix, p["name"]) for p in figures.get("projects", []) for prefix in mdreport.SECTION_PREFIXES]


def _flatten_visibility(per_project: dict[str, tuple[str, list[str], str]]) -> dict[str, Any]:
    from ..reports import mdreport

    out: dict[str, Any] = {}
    for name, (goal, stages, ach) in per_project.items():
        out[mdreport.key("Sprint goal", name)] = goal
        out[mdreport.key("Workflow", name)] = " → ".join(stages)
        out[mdreport.key("Key achievement", name)] = ach
    return out


def figures_only_visibility(figures: dict) -> dict[str, Any]:
    from ..reports import mdreport

    return _flatten_visibility({p["name"]: (mdreport.fallback_goal(p), mdreport.fallback_workflow(p), mdreport.fallback_achievement(p)) for p in figures.get("projects", [])})


def build_visibility_prompt(figures: dict, template: dict, note: str | None, previous: dict | None) -> str:
    clean = sanitize_figures(figures)
    projects = [
        {k: p[k] for k in ("name", "planned", "completed", "in_progress", "pending", "activities", "deliverables", "work_distribution") if k in p}
        for p in clean.get("projects", [])
    ]
    parts = [
        f"Report: {template.get('name', 'Project visibility report')}",
        f"Tone instructions: {template.get('tone_instructions') or 'Professional and concise.'}",
        "PROJECTS:\n" + json.dumps(projects, indent=1, default=str),
    ]
    if previous and note:
        parts.append("PREVIOUS DRAFT:\n" + json.dumps({k: v for k, v in previous.items() if not k.startswith("_")}, indent=1))
    if note:
        parts.append(f"REVIEWER NOTE (apply this to the redraft): {note}")
    return "\n\n".join(parts)


def parse_visibility_output(raw: str, figures: dict) -> dict[str, Any]:
    from ..reports import mdreport

    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError("model returned no JSON")
    data = json.loads(m.group(0))
    got = data.get("projects", {})
    if not isinstance(got, dict):
        raise ValueError("model JSON has no projects object")
    per: dict[str, tuple[str, list[str], str]] = {}
    questions = [str(q) for q in data.get("questions", []) if q]
    for p in figures.get("projects", []):
        item = got.get(p["name"]) or {}
        goal = str(item.get("sprint_goal") or "").strip()
        stages = [str(x).strip() for x in (item.get("workflow") or []) if str(x).strip()]
        ach = str(item.get("key_achievement") or "").strip()
        if not (goal and stages and ach):
            questions.append(f"The model did not return all texts for “{p['name']}”; the missing parts use a figures-based fallback.")
        per[p["name"]] = (goal or mdreport.fallback_goal(p), stages or mdreport.fallback_workflow(p), ach or mdreport.fallback_achievement(p))
    out = _flatten_visibility(per)
    if questions:
        out["_questions"] = questions
    return out


def draft_report_text(
    figures: dict, template: dict, note: str | None = None, previous: dict | None = None, figures_only: bool = False,
    llm: LLMConfig | None | str = "platform",  # tests / future callers may pass a resolved config
) -> tuple[dict[str, Any], str]:
    """Returns (text per section, provider). `llm` is the resolved config; by default it is looked up from the environment (resolve_config). Raises if a provider is configured but the call fails (the worker retries 3 times, then marks the
    run failed). With no provider the draft is built from the figures only."""
    sections: list[str] = list(template.get("sections", []))
    cfg = resolve_config() if llm == "platform" else llm
    if template.get("base_report") == "visibility":  # per-project sentences instead of the template's section list
        if figures_only or cfg is None:
            return figures_only_visibility(figures), "figures_only"
        raw = _call_model(VIS_SYSTEM, build_visibility_prompt(figures, template, note, previous), cfg)  # type: ignore[arg-type]
        return parse_visibility_output(raw, figures), cfg.provider
    if figures_only or cfg is None:
        return figures_only_text(figures, sections), "figures_only"
    raw = _call_model(SYSTEM_PROMPT, build_user_prompt(figures, template, note, previous), cfg)  # type: ignore[arg-type]
    return parse_model_output(raw, sections), cfg.provider
