"""Admin usage page data: how the AI features behave for this company this month (from ai_calls, ai_feedback, ai_reports)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from ..ai import policy
from ..config import get_settings
from ..deps import Ctx, require
from ..models import AiCall, AiFeedback

router = APIRouter(tags=["ai-admin"])


@router.get("/ai/usage")
def usage(ctx: Ctx = Depends(require("settings.manage"))):
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    calls = ctx.db.execute(select(AiCall).where(AiCall.created_at >= start)).scalars().all()
    n = len(calls)
    ok = [c for c in calls if c.error_code is None]
    checked = sum((c.verifier or {}).get("checked", 0) for c in ok)
    failed = sum((c.verifier or {}).get("failed", 0) for c in ok)
    lat = sorted(c.latency_ms for c in ok)
    votes = ctx.db.execute(select(AiFeedback.rating, func.count()).where(AiFeedback.created_at >= start).group_by(AiFeedback.rating)).all()
    up, down = next((v for r, v in votes if r > 0), 0), next((v for r, v in votes if r < 0), 0)
    tokens = sum(c.input_tokens + c.output_tokens for c in calls)
    budget = get_settings().ai_monthly_token_budget
    return {
        "since": start.date().isoformat(), "status": policy.unavailable_reason(ctx.company_id) or "ready", "enabled": ctx.company.ai_enabled,
        "calls": n, "errors": n - len(ok), "tokens": {"input": sum(c.input_tokens for c in calls), "output": sum(c.output_tokens for c in calls), "cached": sum(c.cached_tokens for c in calls)},
        "budget_used_pct": round(tokens / budget * 100, 1) if budget else None,
        "grounding_pass_rate": round((checked - failed) / checked, 3) if checked else None,
        "fallback_rate": round(sum(1 for c in ok if c.fallback) / len(ok), 3) if ok else None,
        "repair_rate": round(sum(1 for c in ok if c.repaired) / len(ok), 3) if ok else None,
        "p95_latency_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
        "thumbs": {"up": up, "down": down},
        "quota": {"reports_per_day": ctx.company.ai_daily_report_quota, "turns_per_day": ctx.company.ai_daily_turn_quota},
    }
