"""AI assistant (read-only): status + quick actions, chat over server-sent events, feedback on answers, and the person's conversations
(a history they can reopen, rename and delete; nobody else, admins included, can read them)."""

import json
import queue
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from ..ai import policy
from ..ai.assistant import quick, service
from ..deps import Ctx, require
from ..errors import not_found
from ..models import AiConversation, AiFeedback, AiMessage

router = APIRouter(tags=["assistant"])
PAGES = ("dashboard", "tasks", "my-day", "check-ins", "other")
RESUME_WITHIN = timedelta(hours=2)  # opening the panel continues the last conversation only if it was active this recently; otherwise a fresh chat
HISTORY_LIMIT = 100


def _status(ctx: Ctx) -> dict[str, Any]:
    reason = policy.unavailable_reason(ctx.company_id, "assistant")
    return {"status": "ready" if reason is None else "unavailable", "reason": reason, "input_enabled": reason is None, "quick_actions_enabled": reason in (None, "not_configured", "provider_down")}


@router.get("/assistant/status")
def status(page: str = "other", ctx: Ctx = Depends(require("assistant.use"))):
    page = page if page in PAGES else "other"
    st = _status(ctx)
    conv = ctx.db.execute(select(AiConversation).where(AiConversation.user_id == ctx.me.id).order_by(AiConversation.updated_at.desc()).limit(1)).scalar_one_or_none()
    if conv is not None and datetime.now(UTC) - conv.updated_at > RESUME_WITHIN:
        conv = None  # an old thread is not dragged into today's questions: it waits in the history
    messages = _messages(ctx, conv.id)[-40:] if conv else []
    return {**st, "cards": quick.cards_for(page) if st["quick_actions_enabled"] else [{**c, "enabled": False} for c in quick.cards_for(page)],
            "conversation_id": str(conv.id) if conv else None, "conversation_title": conv.title if conv else "", "messages": messages}


def _messages(ctx: Ctx, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = ctx.db.execute(select(AiMessage).where(AiMessage.conversation_id == conversation_id).order_by(AiMessage.created_at)).scalars().all()
    rated = dict(ctx.db.execute(select(AiFeedback.target_id, AiFeedback.rating).where(
        AiFeedback.target_type == "answer", AiFeedback.created_by == ctx.me.id, AiFeedback.target_id.in_([m.id for m in rows]))).all())  # my own votes, so they show again on reopening
    return [{"id": str(m.id), "role": m.role, "text": m.text, "card": m.card, "created_at": m.created_at.isoformat(),
             "rating": None if m.id not in rated else ("up" if rated[m.id] > 0 else "down")} for m in rows]


def _mine(ctx: Ctx, conversation_id: uuid.UUID) -> AiConversation:
    conv = ctx.db.get(AiConversation, conversation_id)
    if conv is None or conv.user_id != ctx.me.id:
        raise not_found("Conversation")
    return conv


@router.get("/assistant/conversations")
def list_conversations(ctx: Ctx = Depends(require("assistant.use"))):
    """My conversations, newest first. Old ones disappear with the 30-day retention of assistant records."""
    counts = select(AiMessage.conversation_id, func.count().label("n")).group_by(AiMessage.conversation_id).subquery()
    rows = ctx.db.execute(
        select(AiConversation, func.coalesce(counts.c.n, 0)).outerjoin(counts, counts.c.conversation_id == AiConversation.id)
        .where(AiConversation.user_id == ctx.me.id).order_by(AiConversation.updated_at.desc()).limit(HISTORY_LIMIT)
    ).all()
    untitled = [c.id for c, _ in rows if not c.title]  # threads from before titles existed: use their first question
    first: dict[uuid.UUID, str] = {}
    if untitled:
        for cid, text in ctx.db.execute(select(AiMessage.conversation_id, AiMessage.text).where(AiMessage.conversation_id.in_(untitled), AiMessage.role == "user").order_by(AiMessage.created_at)):
            first.setdefault(cid, text)
    return {"items": [{"id": str(c.id), "title": c.title or service.make_title(first.get(c.id, "")) or "New chat", "updated_at": c.updated_at.isoformat(), "message_count": n} for c, n in rows]}


@router.get("/assistant/conversations/{conversation_id}")
def get_conversation(conversation_id: uuid.UUID, ctx: Ctx = Depends(require("assistant.use"))):
    conv = _mine(ctx, conversation_id)
    messages = _messages(ctx, conv.id)
    return {"id": str(conv.id), "title": conv.title, "messages": messages, "full": len(messages) >= service.MAX_CONVERSATION_MESSAGES}


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)


@router.patch("/assistant/conversations/{conversation_id}")
def rename_conversation(conversation_id: uuid.UUID, body: RenameIn, ctx: Ctx = Depends(require("assistant.use"))):
    conv = _mine(ctx, conversation_id)
    conv.title = " ".join(body.title.split())
    ctx.db.commit()
    return {"id": str(conv.id), "title": conv.title}


@router.delete("/assistant/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, ctx: Ctx = Depends(require("assistant.use"))):
    ctx.db.delete(_mine(ctx, conversation_id))  # its messages go with it
    ctx.db.commit()


@router.delete("/assistant/conversations", status_code=204)
def clear_history(ctx: Ctx = Depends(require("assistant.use"))):
    """Delete all of my conversations."""
    ctx.db.execute(delete(AiConversation).where(AiConversation.user_id == ctx.me.id))
    ctx.db.commit()


class ChatIn(BaseModel):
    message: str = Field(default="", max_length=1000)
    quick_action: str | None = None
    conversation_id: uuid.UUID | None = None
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/assistant/chat")
def chat(body: ChatIn, ctx: Ctx = Depends(require("assistant.use"))):
    if not body.quick_action and len(body.message.strip()) < 2:
        from ..errors import bad_request

        raise bad_request("empty_message", "Ask a question or pick one of the suggestions.")
    page = str(body.context.get("page") or "other")
    context = {k: v for k, v in body.context.items() if k in ("project_id", "days") and v}
    plan = service.prepare(ctx, body.message, body.quick_action, body.conversation_id, page if page in PAGES else "other", context)
    events: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

    def work() -> None:
        try:
            service.run_turn(plan, lambda name, data: events.put((name, data)))
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream() -> Iterator[str]:
        while (item := events.get()) is not None:
            yield f"event: {item[0]}\ndata: {json.dumps(item[1])}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class FeedbackIn(BaseModel):
    rating: str = Field(pattern="^(up|down)$")
    reason: str = Field(default="", max_length=500)


@router.post("/assistant/messages/{message_id}/feedback", status_code=204)
def message_feedback(message_id: uuid.UUID, body: FeedbackIn, ctx: Ctx = Depends(require("assistant.use"))):
    msg = ctx.db.get(AiMessage, message_id)
    if msg is None or msg.user_id != ctx.me.id or msg.role != "assistant":
        raise not_found("Message")
    rating = 1 if body.rating == "up" else -1
    mine = ctx.db.execute(select(AiFeedback).where(AiFeedback.target_type == "answer", AiFeedback.target_id == msg.id, AiFeedback.created_by == ctx.me.id)).scalar_one_or_none()
    if mine is None:
        ctx.db.add(AiFeedback(company_id=ctx.company_id, target_type="answer", target_id=msg.id, rating=rating, reason=body.reason.strip(), created_by=ctx.me.id))
    else:
        mine.rating, mine.reason = rating, body.reason.strip()
    ctx.db.commit()
