"""One ai_calls row and one log line per model call: company, surface, prompt version, model, tokens, latency, verifier summary, fallback.
Never prompt text, never names. Tracing must not break a call, so every failure here is swallowed (and logged)."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update

from ..config import get_settings
from ..db import new_session
from ..models import AiCall

log = logging.getLogger("ai")
_alerted: set[tuple[str, str]] = set()  # (company, month) already warned about the budget


def record(company_id: str | uuid.UUID | None, surface: str, info: Any, error_code: str | None = None) -> str | None:
    if company_id is None:
        return None
    call_id = uuid.uuid4()
    try:
        db = new_session(company_id)
        try:
            u = info.usage
            db.add(AiCall(
                id=call_id, company_id=uuid.UUID(str(company_id)), surface=surface, provider=info.provider, model=info.model, prompt_version=info.prompt_version,
                input_tokens=u["input"], output_tokens=u["output"], cached_tokens=u["cached"], latency_ms=info.latency_ms, repaired=info.repaired, error_code=error_code,
            ))
            db.commit()
            _budget_alert(db, company_id)
        finally:
            db.close()
        log.info("ai_call surface=%s provider=%s model=%s prompt=%s in=%s out=%s cached=%s ms=%s repaired=%s error=%s company=%s", surface, info.provider, info.model,
                 info.prompt_version, u["input"], u["output"], u["cached"], info.latency_ms, info.repaired, error_code, company_id)
        return str(call_id)
    except Exception:  # noqa: BLE001
        log.exception("could not record ai call")
        return None


def update_outcome(company_id: str | uuid.UUID | None, call_id: str | None, verifier: dict[str, Any] | None, fallback: bool) -> None:
    """After verification: how many texts were checked / failed and whether built-in wording was used. Counts only."""
    if company_id is None or call_id is None:
        return
    try:
        db = new_session(company_id)
        try:
            db.execute(update(AiCall).where(AiCall.id == uuid.UUID(call_id)).values(verifier=verifier, fallback=fallback))
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        log.exception("could not update ai call")


def month_tokens(db, company_id: str | uuid.UUID) -> int:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = db.execute(select(func.coalesce(func.sum(AiCall.input_tokens + AiCall.output_tokens), 0)).where(AiCall.created_at >= start)).scalar_one()
    return int(total)


def _budget_alert(db, company_id) -> None:
    budget = get_settings().ai_monthly_token_budget
    if not budget:
        return
    month = datetime.now(UTC).strftime("%Y-%m")
    key = (str(company_id), month)
    if key in _alerted:
        return
    used = month_tokens(db, company_id)
    if used >= 0.8 * budget:
        _alerted.add(key)
        log.warning("ai_budget_alert company=%s month=%s used=%s budget=%s (80%% reached)", company_id, month, used, budget)
