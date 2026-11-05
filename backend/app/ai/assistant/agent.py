"""The agent loop for free-text questions. Python owns the control flow (design §5): the model picks the next step as structured output, code runs the
tool, and the final answer is released only sentence by sentence after each sentence passes the grounding check against THIS turn's tool results.

Budgets per turn: 6 tool calls, ~10K tokens of tool results, 30 s wall clock, at most 2 clarifying questions per conversation, 1 repair per structural error."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from ...services import ai
from .. import budget, gateway, prompts, verify
from . import tools
from .coder import NameCoder
from .quick import LABEL

MAX_TOOL_CALLS = 6
MAX_TOOL_TOKENS = 10_000
MAX_SECONDS = 30
MAX_STEPS = 8
MAX_CLARIFICATIONS = 2
MAX_SENTENCES = 8
UNCONFIRMED = "I could not confirm one detail against your data, so I left it out."
GIVE_UP = "I could not finish looking that up. Try a narrower question, for example one project or one week."


class StepOut(BaseModel):
    action: Literal["tool", "answer", "clarify"]
    tool: str | None = None
    args_json: str | None = None
    sentences: list[str] | None = None
    question: str | None = None


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STEP_SCHEMA = _obj({
    "action": {"type": "string", "enum": ["tool", "answer", "clarify"]}, "tool": {"type": ["string", "null"]}, "args_json": {"type": ["string", "null"]},
    "sentences": {"type": ["array", "null"], "items": {"type": "string"}}, "question": {"type": ["string", "null"]},
})


@dataclass
class Turn:
    sentences: list[dict[str, Any]] = field(default_factory=list)  # [{"text", "grounded"}]
    clarify: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)  # coded results, for evidence and the sources card
    stats: dict[str, int] = field(default_factory=dict)


def system_prompt(perms: frozenset[str]) -> str:
    listing = "\n".join(f"- {n}: {t.doc}" for n, t in tools.available(perms).items())
    return prompts.load("assistant_v1", TOOLS=listing).text


PROMPT_ID = "assistant_v1"


def _prompt(today: str, page: str, summary: dict, history: list[dict], calls: list[dict], question: str, note: str | None) -> str:
    parts = [f"TODAY: {today}", f"PAGE THE USER IS ON: {page or 'unknown'}", "CONVERSATION CONTEXT: " + json.dumps(summary, default=str)]
    if history:
        parts.append("CONVERSATION SO FAR (oldest first):\n" + "\n".join(f"{m['role']}: {m['text']}" for m in history))
    if calls:
        parts.append("TOOL RESULTS THIS TURN:\n" + json.dumps(calls, default=str))
    parts.append(f"QUESTION: {question}")
    if note:
        parts.append(note)
    return "\n\n".join(parts)


def verify_sentences(sentences: list[str], calls: list[dict], coder: NameCoder, year: int | None) -> list[dict[str, Any]]:
    """Each sentence is checked on its own; a failed one is replaced, never shown. Names are restored only after the check."""
    ev = verify.build_evidence([c for c in calls if "error" not in c], coder.back)
    out = []
    for s in sentences[:MAX_SENTENCES]:
        s = s.strip()
        if not s:
            continue
        ok = verify.verify_text(s, ev, year).passed
        out.append({"text": coder.restore(s) if ok else UNCONFIRMED, "grounded": ok})
    return out


def run_agent(tc: tools.ToolCtx, cfg: ai.LLMConfig, company_id: str, question: str, page: str, history: list[dict], summary: dict, coder: NameCoder,
              emit: Callable[[str, dict], None]) -> Turn:
    turn = Turn()
    available = tools.available(tc.perms)
    system = system_prompt(tc.perms)
    coded_q = coder.code_text(question)
    coded_history = [{"role": m["role"], "text": coder.code_text(m["text"])} for m in history]
    started = time.monotonic()
    tool_tokens = 0
    note: str | None = None
    for _ in range(MAX_STEPS):
        if time.monotonic() - started > MAX_SECONDS:
            break
        emit("status", {"text": "Thinking…"})
        user = _prompt(tc.today.isoformat(), page, summary, coded_history, turn.calls, coded_q, note)
        step, _info = gateway.call_structured(system, user, StepOut, STEP_SCHEMA, "assistant_step", cfg, PROMPT_ID, company_id, "assistant")
        if step.action == "clarify" and step.question:
            if summary.get("clarifications", 0) >= MAX_CLARIFICATIONS:
                note = "You have asked enough questions: answer now with the best supported answer, or say what is missing."
                continue
            turn.clarify = coder.restore(step.question.strip())
            return turn
        if step.action == "answer" and step.sentences:
            turn.sentences = verify_sentences(step.sentences, turn.calls, coder, tc.today.year)
            return turn
        if step.action != "tool" or not step.tool:
            note = "Reply with a tool call, an answer, or one clarifying question."
            continue
        if step.tool not in available:
            note = f"There is no tool called {step.tool}. Available: {', '.join(available)}."
            continue
        if len(turn.calls) >= MAX_TOOL_CALLS or tool_tokens >= MAX_TOOL_TOKENS:
            note = "The tool budget for this turn is used up: answer now from the tool results above, or say what is missing."
            continue
        try:
            args = json.loads(step.args_json or "{}")
        except ValueError:
            args = {}
        emit("status", {"text": f"Checking {LABEL.get(step.tool, step.tool).lower()}…"})
        result = coder.code(tools.run(step.tool, args if isinstance(args, dict) else {}, tc))
        result["args"] = args if isinstance(args, dict) else {}
        tool_tokens += budget.estimate_tokens(json.dumps(result, default=str))
        turn.calls.append(result)
    turn.sentences = [{"text": GIVE_UP, "grounded": True}]
    return turn
