"""Admin usage page data: how the AI features behave for this company over a period (from ai_calls, ai_feedback, ai_messages, ai_reports).
Counts, tokens, timings and ratings only: never prompt or answer text."""

from collections import Counter
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ..ai import policy
from ..config import get_settings
from ..deps import Ctx, require
from ..models import AiCall, AiFeedback, AiMessage, AiReport
from ..services.timeutil import company_now

router = APIRouter(tags=["ai-admin"])
DAYS = {"7": 7, "30": 30, "90": 90}  # the other choice, "month", runs from the 1st of the current month


def _pct(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _percentile(sorted_values: list[int], p: float) -> int | None:
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * p))] if sorted_values else None


@router.get("/ai/usage")
def usage(period: str = Query("month", pattern="^(month|7|30|90)$"), ctx: Ctx = Depends(require("settings.manage"))):
    now = company_now(ctx.company.timezone)
    today = now.date()
    month_start = datetime.combine(today.replace(day=1), time.min, tzinfo=now.tzinfo)
    first_day = today.replace(day=1) if period == "month" else today - timedelta(days=DAYS[period] - 1)
    start = datetime.combine(first_day, time.min, tzinfo=now.tzinfo)

    calls = ctx.db.execute(select(AiCall).where(AiCall.created_at >= start)).scalars().all()
    n = len(calls)
    ok = [c for c in calls if c.error_code is None]
    checked = sum((c.verifier or {}).get("checked", 0) for c in ok)
    failed = sum((c.verifier or {}).get("failed", 0) for c in ok)
    lat = sorted(c.latency_ms for c in ok)
    tokens_of = lambda c: c.input_tokens + c.output_tokens  # noqa: E731

    # one point per day (days without a call are zeros, so the chart has no gaps)
    per_day: dict = {first_day + timedelta(days=i): {"calls": 0, "errors": 0, "tokens": 0} for i in range((today - first_day).days + 1)}
    for c in calls:
        d = per_day.get(c.created_at.astimezone(now.tzinfo).date())
        if d is not None:
            d["calls"] += 1
            d["errors"] += 1 if c.error_code else 0
            d["tokens"] += tokens_of(c)

    def group(key) -> list[dict]:
        rows: dict = {}
        for c in calls:
            r = rows.setdefault(key(c), {"calls": 0, "errors": 0, "tokens": 0, "latency": []})
            r["calls"] += 1
            r["errors"] += 1 if c.error_code else 0
            r["tokens"] += tokens_of(c)
            if c.error_code is None:
                r["latency"].append(c.latency_ms)
        return [{"name": k, "calls": v["calls"], "errors": v["errors"], "tokens": v["tokens"],
                 "avg_latency_ms": round(sum(v["latency"]) / len(v["latency"])) if v["latency"] else None}
                for k, v in sorted(rows.items(), key=lambda kv: -kv[1]["calls"])]

    votes = ctx.db.execute(select(AiFeedback.rating, func.count()).where(AiFeedback.created_at >= start).group_by(AiFeedback.rating)).all()
    up, down = sum(v for r, v in votes if r > 0), sum(v for r, v in votes if r < 0)
    reasons = ctx.db.execute(
        select(AiFeedback.reason, func.count()).where(AiFeedback.created_at >= start, AiFeedback.rating < 0, AiFeedback.reason != "")
        .group_by(AiFeedback.reason).order_by(func.count().desc()).limit(5)).all()

    day_start = datetime.combine(today, time.min, tzinfo=now.tzinfo)
    turns_today = ctx.db.execute(select(func.count()).select_from(AiMessage).where(AiMessage.role == "user", AiMessage.created_at >= day_start)).scalar_one()
    reports_today = ctx.db.execute(select(func.count()).select_from(AiReport).where(AiReport.created_at >= day_start)).scalar_one()
    month_tokens = ctx.db.execute(select(func.coalesce(func.sum(AiCall.input_tokens + AiCall.output_tokens), 0)).where(AiCall.created_at >= month_start)).scalar_one()
    budget = get_settings().ai_monthly_token_budget

    return {
        "period": period, "since": first_day.isoformat(), "status": policy.unavailable_reason(ctx.company_id) or "ready", "enabled": ctx.company.ai_enabled,
        "calls": n, "errors": n - len(ok), "success_rate": _pct(len(ok), n),
        "tokens": {"input": sum(c.input_tokens for c in calls), "output": sum(c.output_tokens for c in calls), "cached": sum(c.cached_tokens for c in calls)},
        "budget_used_pct": round(month_tokens / budget * 100, 1) if budget else None,  # the budget is monthly, whatever period is shown
        "budget_tokens": budget or None, "month_tokens": int(month_tokens),
        "grounding_pass_rate": round((checked - failed) / checked, 3) if checked else None,
        "fallback_rate": _pct(sum(1 for c in ok if c.fallback), len(ok)),
        "repair_rate": _pct(sum(1 for c in ok if c.repaired), len(ok)),
        "p95_latency_ms": _percentile(lat, 0.95),
        "latency_ms": {"avg": round(sum(lat) / len(lat)) if lat else None, "p50": _percentile(lat, 0.5), "p95": _percentile(lat, 0.95)},
        "daily": [{"date": d.isoformat(), **v} for d, v in per_day.items()],
        "by_feature": group(lambda c: c.surface),
        "by_model": group(lambda c: f"{c.provider} · {c.model}"),
        "errors_by_code": [{"code": k, "count": v} for k, v in Counter(c.error_code for c in calls if c.error_code).most_common()],
        "thumbs": {"up": up, "down": down}, "satisfaction": _pct(up, up + down),
        "thumbs_down_reasons": [{"reason": r, "count": k} for r, k in reasons],
        "today": {"turns": turns_today, "reports": reports_today},
        "quota": {"reports_per_day": ctx.company.ai_daily_report_quota, "turns_per_day": ctx.company.ai_daily_turn_quota},
    }
