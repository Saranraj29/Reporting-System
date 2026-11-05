"""AI assistant (read-only): status + quick actions, chat over server-sent events, feedback on answers, the current conversation."""

import json
import queue
import threading
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..ai import policy
from ..ai.assistant import quick, service
from ..deps import Ctx, require
from ..errors import not_found
from ..models import AiConversation, AiFeedback, AiMessage

router = APIRouter(tags=["assistant"])
PAGES = ("dashboard", "tasks", "my-day", "check-ins", "other")


def _status(ctx: Ctx) -> dict[str, Any]:
    reason = policy.unavailable_reason(ctx.company_id, "assistant")
    return {"status": "ready" if reason is None else "unavailable", "reason": reason, "input_enabled": reason is None, "quick_actions_enabled": reason in (None, "not_configured", "provider_down")}


@router.get("/assistant/status")
def status(page: str = "other", ctx: Ctx = Depends(require("assistant.use"))):
    page = page if page in PAGES else "other"
    st = _status(ctx)
    conv = ctx.db.execute(select(AiConversation).where(AiConversation.user_id == ctx.me.id).order_by(AiConversation.updated_at.desc()).limit(1)).scalar_one_or_none()
    messages = []
    if conv is not None:
        rows = ctx.db.execute(select(AiMessage).where(AiMessage.conversation_id == conv.id).order_by(AiMessage.created_at.desc()).limit(40)).scalars().all()
        messages = [{"id": str(m.id), "role": m.role, "text": m.text, "card": m.card, "created_at": m.created_at.isoformat()} for m in reversed(rows)]
    return {**st, "cards": quick.cards_for(page) if st["quick_actions_enabled"] else [{**c, "enabled": False} for c in quick.cards_for(page)],
            "conversation_id": str(conv.id) if conv else None, "messages": messages}


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
