"""Versioned prompt files. The file name carries the version (plan_v1.md); the id is recorded on every AI call and report,
so a bad prompt can be found and its output regenerated. Changing a prompt means a new file/version and an evaluation run."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    id: str  # e.g. "plan_v1"
    text: str


@lru_cache
def load(name: str, **fill: str) -> Prompt:
    raw = (DIR / f"{name}.md").read_text(encoding="utf-8").strip()
    for key, value in fill.items():
        raw = raw.replace("{{" + key + "}}", value)
    return Prompt(name, raw)
