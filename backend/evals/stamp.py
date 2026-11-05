"""Prompt files must not change without an evaluation run. After the golden set passes with the new prompt, run `python -m evals.stamp`
and commit prompt_stamps.json; tests/test_evals_offline.py fails while a prompt file and its stamp disagree."""

import hashlib
import json
from pathlib import Path

PROMPTS = Path(__file__).parent.parent / "app" / "ai" / "prompts"
STAMPS = Path(__file__).parent / "prompt_stamps.json"


def current() -> dict[str, str]:
    return {p.stem: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(PROMPTS.glob("*.md"))}


if __name__ == "__main__":
    STAMPS.write_text(json.dumps(current(), indent=1) + "\n")
    print("stamped", ", ".join(current()))
