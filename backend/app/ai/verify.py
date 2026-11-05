"""Grounding check (level 1, pure code): every number, date, quoted task title and person code in a piece of model text must exist in the
facts the model was given. A text that fails is replaced by built-in wording and flagged; it is never shown."""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .redact import scrub

NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s?(%?)")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_RE = "|".join(MONTHS)
TEXT_DATE = re.compile(rf"\b(?:(\d{{1,2}})\s+({MONTH_RE})[a-z]*(?:,?\s+(\d{{4}}))?|({MONTH_RE})[a-z]*\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?)\b")
QUOTED = re.compile(r"[“\"]([^”\"\n]{2,160})[”\"]")
CODE = re.compile(r"\bPerson [A-Z0-9]+\b")


@dataclass
class Flag:
    check: str  # number | date | title | person
    value: str


@dataclass
class VerificationResult:
    passed: bool
    flags: list[Flag] = field(default_factory=list)
    level: int = 1  # 1 = code check only

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "level": self.level, "flags": [{"check": f.check, "value": f.value} for f in self.flags]}


class Evidence:
    """Everything the model was allowed to see, indexed for the checks."""

    def __init__(self, view: Any, codes: set[str]):
        self.codes = codes
        self.strings: list[str] = []
        self.numbers: set[float] = set()
        self.dates: set[date] = set()
        self._walk(view)
        t = view.get("totals") if isinstance(view, dict) else None
        if isinstance(t, dict) and t.get("planned"):  # figures the code derives from the facts: overall % done, open tasks
            self.numbers.update({float(round(t["completed"] / t["planned"] * 100)), float(t["planned"] - t["completed"])})
        self.lower = [s.casefold() for s in self.strings]

    def _walk(self, o: Any) -> None:
        if isinstance(o, bool) or o is None:
            return
        if isinstance(o, (int, float)):
            self.numbers.add(float(o))
        elif isinstance(o, str):
            self.strings.append(o)
            for m in ISO_DATE.finditer(o):
                try:
                    self.dates.add(date(int(m[1]), int(m[2]), int(m[3])))
                except ValueError:
                    pass
            for n in _numbers_in(ISO_DATE.sub(" ", o)):
                self.numbers.add(n)
        elif isinstance(o, list):
            self.numbers.add(float(len(o)))  # "3 tasks are overdue" = the length of the overdue list
            for x in o:
                self._walk(x)
        elif isinstance(o, dict):
            for k, v in o.items():
                self._walk(k)
                self._walk(v)

    def has_title(self, title: str) -> bool:
        t = title.strip().casefold()
        return any(t in s for s in self.lower)

    def number_ok(self, x: float, decimals: int) -> bool:
        if x in self.numbers:
            return True
        # rounding is allowed: 40 % for 39.6 %, 10 h for 9.75 h
        return any(round(n, decimals) == x or (decimals == 0 and abs(n - x) < 0.5 + 1e-9) for n in self.numbers if abs(n - x) <= 1.0)

    def date_ok(self, d: date) -> bool:
        return d in self.dates or any(d.month == e.month and d.day == e.day and d.year in (e.year, 0) for e in self.dates)


def _numbers_in(text: str) -> list[float]:
    out = []
    for m in NUMBER.finditer(text):
        whole = m[1].replace(",", "")
        out.append(float(f"{whole}.{m[2]}") if m[2] else float(whole))
    return out


def build_evidence(view: Any, back: dict[str, str]) -> Evidence:
    return Evidence(view, set(back))


def verify_text(text: str, ev: Evidence, default_year: int | None = None) -> VerificationResult:
    flags: list[Flag] = []
    if scrub(text) != text:  # the facts were scrubbed, so an e-mail, phone number or @handle in the answer was made up
        flags.append(Flag("pii", "personal contact detail"))
    rest = text
    for m in QUOTED.finditer(text):
        if not ev.has_title(m[1]):
            flags.append(Flag("title", m[1]))
    for c in CODE.findall(text):
        if c not in ev.codes:
            flags.append(Flag("person", c))
    # dates first, so their digits are not read as numbers
    for m in ISO_DATE.finditer(text):
        try:
            if not ev.date_ok(date(int(m[1]), int(m[2]), int(m[3]))):
                flags.append(Flag("date", m[0]))
        except ValueError:
            flags.append(Flag("date", m[0]))
    rest = ISO_DATE.sub(" ", rest)
    for m in TEXT_DATE.finditer(rest):
        day, mon = (m[1], m[2]) if m[1] else (m[5], m[4])
        year = m[3] or m[6]
        try:
            d = date(int(year) if year else (default_year or 0) or 2000, MONTHS.index(mon) + 1, int(day))
        except ValueError:
            flags.append(Flag("date", m[0]))
            continue
        if not any(d.month == e.month and d.day == e.day and (not year or d.year == e.year) for e in ev.dates):
            flags.append(Flag("date", m[0]))
    rest = TEXT_DATE.sub(" ", rest)
    rest = QUOTED.sub(" ", rest)  # numbers inside a quoted title were checked with the title
    rest = CODE.sub(" ", rest)
    for m in NUMBER.finditer(rest):
        whole = m[1].replace(",", "")
        x = float(f"{whole}.{m[2]}") if m[2] else float(whole)
        if not ev.number_ok(x, len(m[2] or "")):
            flags.append(Flag("number", m[0].strip()))
    return VerificationResult(not flags, flags)
