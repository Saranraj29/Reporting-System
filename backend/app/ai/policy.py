"""Who may use AI right now: platform switch (AI_ENABLED), the company's own switch, and the provider breaker. Flags are cached for 60 s so a
switch takes effect without a restart. When AI is off, callers use their built-in wording: the app keeps working."""

import time
import uuid

from sqlalchemy import select

from ..config import get_settings
from ..db import new_session
from ..models import Company
from ..services import ai
from .breaker import breaker

TTL = 60.0
_cache: dict[str, tuple[float, bool, bool]] = {}  # company -> (loaded_at, ai_enabled, assistant_enabled)


def clear_cache() -> None:
    _cache.clear()


def _flags(company_id: str | uuid.UUID) -> tuple[bool, bool]:
    key = str(company_id)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1], hit[2]
    db = new_session(company_id)
    try:
        row = db.execute(select(Company.ai_enabled, Company.ai_assistant_enabled).where(Company.id == uuid.UUID(key))).first()
    finally:
        db.close()
    flags = (bool(row[0]), bool(row[1])) if row else (True, True)
    _cache[key] = (time.monotonic(), *flags)
    return flags


def enabled(company_id: str | uuid.UUID | None, capability: str = "reports") -> bool:
    """Platform flag AND company flag (AND the assistant flag for the assistant)."""
    if not get_settings().ai_enabled:
        return False
    if company_id is None:
        return True
    ai_on, assistant_on = _flags(company_id)
    return ai_on and (assistant_on if capability == "assistant" else True)


def active_config(company_id: str | uuid.UUID | None, capability: str = "reports") -> ai.LLMConfig | None:
    """The provider config to use, or None = use the built-in path (no key, switched off, or the breaker is open)."""
    if not enabled(company_id, capability):
        return None
    cfg = ai.resolve_config()
    if cfg is None or not breaker.allow():
        return None
    return cfg


def unavailable_reason(company_id: str | uuid.UUID | None, capability: str = "reports") -> str | None:
    """For the UI status chip: why AI is not available, or None when it is."""
    if not get_settings().ai_enabled or not enabled(company_id, capability):
        return "off"
    if ai.resolve_config() is None:
        return "not_configured"
    if breaker.is_open:
        return "provider_down"
    return None
