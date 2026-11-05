"""Personal data never reaches the model: people become codes ("Person A", restored afterwards) and anything that looks like an email
address, phone number, @handle or a link with a query string is replaced by a placeholder, wherever it was typed (task titles, requests, samples)."""

import copy
import re
import string
from typing import Any

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
HANDLE = re.compile(r"(?<![\w.@])@[A-Za-z0-9_]{2,}")
LINK_WITH_QUERY = re.compile(r"https?://[^\s<>\"']*\?[^\s<>\"']*")
PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{7,}\d(?![\w])")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _phone(m: re.Match[str]) -> str:
    raw = m.group(0)
    if ISO_DATE.search(raw) or sum(c.isdigit() for c in raw) < 9:  # dates (and runs that contain one) are not phone numbers
        return raw
    return "[phone]"


def scrub(text: str) -> str:
    """Emails, links with query strings, phone numbers and @handles -> placeholders."""
    text = EMAIL.sub("[email]", text)
    text = LINK_WITH_QUERY.sub("[link]", text)
    text = HANDLE.sub("[handle]", text)
    return PHONE.sub(_phone, text)


def person_names(facts: dict[str, Any]) -> list[str]:
    return sorted({n for p in facts["projects"] for n in [*(p.get("owners") or []), *(x["name"] for x in p.get("people", []))]}, key=len, reverse=True)


def llm_view(facts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """A copy of the facts for the model: every person replaced by a code, every string scrubbed. Returns (view, code -> name map)."""
    names = person_names(facts)
    codes = {n: f"Person {string.ascii_uppercase[i] if i < 26 else i + 1}" for i, n in enumerate(sorted(names))}
    pattern = re.compile("|".join(re.escape(n) for n in names)) if names else None

    def walk(o: Any) -> Any:
        if isinstance(o, str):
            return scrub(pattern.sub(lambda m: codes[m.group(0)], o) if pattern else o)
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o

    view = walk(copy.deepcopy({k: v for k, v in facts.items() if k not in ("company", "people_filter")}))
    for p in view["projects"]:
        p.pop("id", None)
    return view, {v: k for k, v in codes.items()}


def restore(text: str, back: dict[str, str]) -> str:
    for code in sorted(back, key=len, reverse=True):
        text = text.replace(code, back[code])
    return text
