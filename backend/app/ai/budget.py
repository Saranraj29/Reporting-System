"""Context budget: nothing is cut silently. Lists sent to the model are capped per project and carry their true totals; a request that is
still too large is refused with a clear message instead of a provider error."""

import json
from typing import Any

from ..config import get_settings

CAPS = {"activities": 40, "deliverables": 20, "overdue": 20, "upcoming": 20, "blocked": 20}


class ContextLimitError(Exception):
    """limit.context — the request would not fit; the user must narrow projects or period. Never retried."""

    code = "limit.context"
    user_message = "This report covers too much data for the AI to read at once. Choose fewer projects or a shorter period and try again."


def estimate_tokens(*parts: str) -> int:
    return sum(len(p) for p in parts) // 4


def cap_view(view: dict[str, Any]) -> dict[str, Any]:
    """Per-project row caps; the full count of every capped list is kept as `<name>_total` so the model still knows the real size."""
    for p in view.get("projects", []):
        for name, cap in CAPS.items():
            items = p.get(name)
            if isinstance(items, list) and len(items) > cap:
                p[f"{name}_total"] = len(items)
                p[name] = items[:cap]
    return view


def check_size(*parts: str) -> int:
    n = estimate_tokens(*parts)
    if n > get_settings().ai_max_input_tokens:
        raise ContextLimitError(f"estimated {n} tokens")
    return n


def view_tokens(view: dict[str, Any]) -> int:
    return estimate_tokens(json.dumps(view, default=str))
