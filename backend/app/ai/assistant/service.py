"""One assistant turn: quotas, conversation state, the code-owned workflow or the agent loop, grounding, persistence, and the events the panel shows.
`prepare` runs inside the request (it can refuse with a normal HTTP error); `run_turn` runs in a worker thread with its own tenant session and pushes events."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select, text

from ...db import new_session
from ...deps import Ctx
from ...errors import ApiError
from ...models import AiConversation, AiMessage
from ...services.timeutil import company_now
from .. import budget, gateway, policy, verify
from . import quick, tools
from .agent import GIVE_UP, PROMPT_ID, UNCONFIRMED, Turn, run_agent
from .coder import NameCoder

log = logging.getLogger("ai")
USER_PER_MINUTE = 10
HISTORY_MESSAGES = 12


@dataclass
class TurnPlan:
    company_id: str
    user_id: uuid.UUID
    perms: frozenset[str]
    conversation_id: uuid.UUID
    message_text: str
    quick_action: str | None
    page: str
    context: dict[str, Any]
    history: list[dict[str, str]]
    summary: dict[str, Any]
    today: date
    cfg: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


def prepare(ctx: Ctx, message: str, quick_action: str | None, conversation_id: uuid.UUID | None, page: str, context: dict[str, Any]) -> TurnPlan:
    if not policy.enabled(ctx.company_id, "assistant"):
        raise ApiError(503, "assistant.unavailable", "The assistant is switched off for your company. The app works as normal.")
    cfg = policy.active_config(ctx.company_id, "assistant")
    if quick_action is None and cfg is None:
        raise ApiError(503, "assistant.unavailable", "The assistant cannot answer free questions right now. The quick actions still work.")
    if quick_action is not None and quick_action not in quick.WORKFLOWS:
        raise ApiError(400, "invalid_quick_action", "That quick action is not available yet.")
    now = company_now(ctx.company.timezone)
    day_start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    minute_ago = datetime.now(now.tzinfo) - timedelta(seconds=60)
    q = select(func.count()).select_from(AiMessage).where(AiMessage.role == "user")
    if ctx.db.execute(q.where(AiMessage.user_id == ctx.me.id, AiMessage.created_at >= minute_ago)).scalar_one() >= USER_PER_MINUTE:
        raise ApiError(429, "rate.user", "You are asking very quickly. Wait a moment and try again.")
    if ctx.db.execute(q.where(AiMessage.created_at >= day_start)).scalar_one() >= ctx.company.ai_daily_turn_quota:
        raise ApiError(429, "quota.turns", f"Your company has reached today's limit of {ctx.company.ai_daily_turn_quota} assistant questions. Try again tomorrow.")
    conv = ctx.db.get(AiConversation, conversation_id) if conversation_id else None
    if conv is None or conv.user_id != ctx.me.id:
        conv = AiConversation(company_id=ctx.company_id, user_id=ctx.me.id, summary={})
        ctx.db.add(conv)
        ctx.db.flush()
    history = [{"role": m.role, "text": m.text} for m in reversed(ctx.db.execute(
        select(AiMessage).where(AiMessage.conversation_id == conv.id).order_by(AiMessage.created_at.desc()).limit(HISTORY_MESSAGES)).scalars().all())]
    shown = message.strip() if quick_action is None else quick.REQUEST_TEXT[quick_action]
    ctx.db.add(AiMessage(company_id=ctx.company_id, conversation_id=conv.id, user_id=ctx.me.id, role="user", text=shown))
    ctx.db.commit()
    return TurnPlan(str(ctx.company_id), ctx.me.id, ctx.perms, conv.id, shown, quick_action, page, context, history, dict(conv.summary or {}), now.date(), cfg)


def _card(calls: list[dict[str, Any]], restore: Callable[[str], str]) -> dict[str, Any] | None:
    """The sources card is built by code from the tool results, never from model prose."""
    sources, project_ids, days = [], [], None
    for c in calls:
        if "error" in c:
            continue
        items = []
        for r in c.get("rows", [])[:5]:
            title = r.get("title") or r.get("name") or r.get("activity")
            if title:
                items.append({"id": r.get("task_id") or r.get("project_id") or "", "title": restore(str(title))})
        sources.append({"label": quick.LABEL.get(c["tool"], c["tool"]), "as_of": c.get("as_of"), "returned": c.get("returned", 0), "total": c.get("total", 0), "items": items})
        if c["tool"] == "get_project_figures":
            project_ids += [r["project_id"] for r in c["rows"]]
            days = c.get("days")
    if not sources:
        return None
    handoff = {"label": "Open as full report", "path": "/ai-reports", "days": days, "project_ids": project_ids[:20]} if project_ids else None
    return {"kind": "sources", "sources": sources, "handoff": handoff}


def _summary(old: dict, plan: TurnPlan, calls: list[dict], clarified: bool) -> dict[str, Any]:
    """A typed summary built by code (ids, period, assumptions), never free text, carried between turns."""
    s = {k: v for k, v in old.items() if k in ("clarifications",)}
    s["page"] = plan.page
    for k in ("project_id", "days"):
        if plan.context.get(k):
            s[k] = plan.context[k]
    s["last_tools"] = [c["tool"] for c in calls if "tool" in c][-3:]
    if clarified:
        s["clarifications"] = old.get("clarifications", 0) + 1
    return s


def run_turn(plan: TurnPlan, emit: Callable[[str, dict[str, Any]], None]) -> None:
    db = new_session(plan.company_id)
    sentences: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    clarify: str | None = None
    restore: Callable[[str], str] = lambda s: s  # noqa: E731
    try:
        names = [r[0] for r in db.execute(text("SELECT name FROM users"))]
        tc = tools.ToolCtx(db, plan.user_id, plan.perms, plan.today)
        if plan.quick_action:
            emit("status", {"text": "Checking your data…"})
            lines, calls = quick.WORKFLOWS[plan.quick_action](tc, plan.context)
            ev = verify.build_evidence([c for c in calls if "error" not in c], {})
            sentences = [{"text": s if (ok := verify.verify_text(s, ev, plan.today.year).passed) else UNCONFIRMED, "grounded": ok} for s in lines]
        else:
            coder = NameCoder(names)
            restore = coder.restore
            try:
                turn: Turn = run_agent(tc, plan.cfg, plan.company_id, plan.message_text, plan.page, plan.history, plan.summary, coder, emit)
            except budget.ContextLimitError:
                turn = Turn(sentences=[{"text": GIVE_UP, "grounded": True}])
            except gateway.StructuralError:
                turn = Turn(sentences=[{"text": "I could not put together an answer I can stand behind. Try rephrasing, or use one of the quick actions.", "grounded": True}])
            except Exception as exc:  # noqa: BLE001  provider down, timeout, ...
                log.warning("assistant turn failed: %s", type(exc).__name__)
                emit("error", {"code": "assistant.unavailable", "message": "The AI service is not answering right now. The quick actions still work."})
                return
            sentences, calls, clarify = turn.sentences, turn.calls, turn.clarify
        if clarify:
            emit("clarify", {"text": clarify})
        for s in sentences:
            emit("sentence", s)
        card = _card(calls, restore)
        if card:
            emit("card", card)
        body = clarify or "\n".join(s["text"] for s in sentences)
        msg = AiMessage(company_id=uuid.UUID(plan.company_id), conversation_id=plan.conversation_id, user_id=plan.user_id, role="assistant", text=body, card=card,
                        tool_calls=[{"tool": c.get("tool"), "args": c.get("args", {}), "returned": c.get("returned"), "total": c.get("total"), "as_of": c.get("as_of"),
                                     "error": (c.get("error") or {}).get("code")} for c in calls])
        db.add(msg)
        conv = db.get(AiConversation, plan.conversation_id)
        if conv is not None:
            conv.summary = _summary(plan.summary, plan, calls, clarified=bool(clarify))
            conv.updated_at = datetime.now(conv.updated_at.tzinfo) if conv.updated_at else datetime.now()
        db.commit()
        emit("done", {"conversation_id": str(plan.conversation_id), "message_id": str(msg.id), "prompt": PROMPT_ID if not plan.quick_action else "workflow"})
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("assistant turn crashed")
        emit("error", {"code": "assistant.error", "message": "Something went wrong. Please try again."})
    finally:
        db.close()
