"""The one door to the model: structured output (JSON schema, temperature 0), validation in code, ONE repair call, prompt version
and token usage recorded. A second invalid answer raises StructuralError and the caller uses its built-in fallback in the same job attempt.
Provider/transport errors are NOT caught here: they propagate so the job queue can retry them."""

import dataclasses
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from ..services import ai
from . import budget, trace
from .breaker import breaker


class StructuralError(Exception):
    """The model answered twice without valid structured output."""


@dataclass
class CallInfo:
    provider: str
    model: str
    prompt_version: str
    latency_ms: int = 0
    repaired: bool = False
    call_id: str | None = None  # the ai_calls row, so the caller can attach the verifier outcome
    usage: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0, "cached": 0})

    def as_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "prompt_version": self.prompt_version, "latency_ms": self.latency_ms,
                "repaired": self.repaired, "usage": self.usage}


def _parse[T: BaseModel](raw: str, model: type[T]) -> T:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)  # some providers wrap JSON in a fence even in JSON mode
    return model.model_validate(json.loads(text))


def call_structured[T: BaseModel](system: str, user: str, model: type[T], schema: dict[str, Any], schema_name: str, cfg: ai.LLMConfig, prompt_version: str,
                                  company_id: str | None = None, surface: str = "report") -> tuple[T, CallInfo]:
    """One structured call with at most one repair. Returns (validated answer, call info).
    Raises budget.ContextLimitError before calling when the request is too large, and StructuralError after a failed repair."""
    budget.check_size(system, user)
    scfg = dataclasses.replace(cfg, json_schema=schema, schema_name=schema_name, temperature=0.0)
    info = CallInfo(cfg.provider, cfg.model, prompt_version)
    prompt, error = user, ""
    for _ in range(2):
        ai.LAST_USAGE.set(None)
        t0 = time.monotonic()
        try:
            raw = ai._call_model(system, prompt, scfg)
        except Exception:
            breaker.record(False)
            info.latency_ms += int((time.monotonic() - t0) * 1000)
            trace.record(company_id, surface, info, "provider_error")
            raise
        breaker.record(True)
        info.latency_ms += int((time.monotonic() - t0) * 1000)
        used = ai.LAST_USAGE.get()
        if used:
            for k in info.usage:
                info.usage[k] += int(used.get(k, 0))
        try:
            parsed = _parse(raw, model)
            info.call_id = trace.record(company_id, surface, info)
            return parsed, info
        except (ValueError, ValidationError) as exc:  # json.JSONDecodeError is a ValueError
            error = str(exc).replace("\n", " ")[:300]
            info.repaired = True
            prompt = f"{user}\n\nYour previous answer was not valid ({error}). Answer again with ONLY the structure that was asked for."
    trace.record(company_id, surface, info, "invalid_output")
    raise StructuralError(f"model answer invalid after one repair: {error}")
