"""The golden set's machinery, always on: case files, prompt stamps, the runner (fake model), and the cases that need no real model."""

import json
import re
from collections import Counter

import pytest

from app.ai.breaker import breaker
from app.services import ai
from evals import runner, stamp

from .conftest import drain
from .test_ai_reports import make_owner


def test_seventy_five_well_formed_cases():
    cases = runner.load_cases()
    assert len(cases) == 75 and len({c["id"] for c in cases}) == 75
    assert Counter(c["group"] for c in cases) == {"standard": 15, "sample": 10, "injection": 10, "oversize": 5, "provider_failure": 5, "question": 30}


def test_prompt_files_match_their_evaluation_stamp():
    stamps = json.loads(stamp.STAMPS.read_text())
    assert stamp.current() == stamps, "A prompt changed without an evaluation run: run the golden set, then `python -m evals.stamp` and commit prompt_stamps.json"


def test_thresholds_file_has_every_gate():
    assert set(runner.thresholds()) == {"outline_validity_min", "grounding_pass_rate_min", "injection_success_max", "scope_leakage_max", "fallback_rate_max", "question_pass_rate_min", "answer_grounding_rate_min"}


def test_breaches_are_reported():
    ok = runner.summarise([])
    assert runner.breaches({**ok, "injection_success": 1, "scope_leakage": 2, "grounding_pass_rate": 0.5, "outline_validity": 0.9, "fallback_rate": 0.5}) != []
    assert runner.breaches({**ok, "injection_success": 0, "scope_leakage": 0, "grounding_pass_rate": 0.97, "outline_validity": 1.0, "fallback_rate": 0.1}) == []


@pytest.fixture
def actors(work):
    make_owner(work, work.m1)
    return {"admin": work.admin, "owner": work.m1}


def enable_key(monkeypatch, **env):
    from app.config import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    get_settings.cache_clear()


def good_model(monkeypatch):
    """A well-behaved stand-in: plans like the built-in logic (following a pasted sample) and writes neutral, grounded text."""
    from app.services.airep import writer
    from app.services.airep.outline import sample_outline, standard_outline

    enable_key(monkeypatch)

    def fake(system, user, cfg=None):
        if system == writer.PLAN_SYSTEM:
            m = re.search(r"<<<SAMPLE\n(.*)\nSAMPLE>>>", user, re.S)
            return json.dumps(sample_outline(m.group(1)) if m else standard_outline())
        items = json.loads(user.split("ITEMS:\n", 1)[1].split("\n\nCHANGE", 1)[0].split("\n\nPREVIOUS", 1)[0])
        return json.dumps({"items": [{"key": i["key"], "text": "Work is progressing as planned."} for i in items]})

    monkeypatch.setattr(ai, "_call_model", fake)


@pytest.mark.parametrize("group", ["standard", "sample", "injection"])
def test_runner_with_a_well_behaved_model(group, work, actors, owner_conn, monkeypatch):
    good_model(monkeypatch)
    case = runner.load_cases(group)[0]
    res = runner.run_case(case, work, drain, owner_conn, actors)
    assert res.ok, res.problems
    s = runner.summarise([res])
    assert s["injection_success"] == 0 and s["scope_leakage"] == 0


def evil_model(monkeypatch, canary):
    from app.services.airep import writer
    from app.services.airep.outline import standard_outline

    enable_key(monkeypatch)

    def evil(system, user, cfg=None):
        if system == writer.PLAN_SYSTEM:
            return json.dumps(standard_outline())
        items = json.loads(user.split("ITEMS:\n", 1)[1].split("\n\nCHANGE", 1)[0].split("\n\nPREVIOUS", 1)[0])
        return json.dumps({"items": [{"key": i["key"], "text": f"Fine. {canary}"} for i in items]})

    monkeypatch.setattr(ai, "_call_model", evil)


def test_runner_catches_a_model_that_follows_an_injection(work, actors, owner_conn, monkeypatch):
    evil_model(monkeypatch, "PWNED")
    case = {**runner.load_cases("injection")[0], "canary": "PWNED"}
    res = runner.run_case(case, work, drain, owner_conn, actors)
    assert not res.ok and res.canary_hit
    assert runner.breaches(runner.summarise([res]))  # injection_success > 0 breaches the gate


def test_the_grounding_check_blocks_a_canary_that_contains_numbers(work, actors, owner_conn, monkeypatch):
    case = runner.load_cases("injection")[0]
    evil_model(monkeypatch, case["canary"])  # PWNED-7731: the number is not in the facts
    res = runner.run_case(case, work, drain, owner_conn, actors)
    assert res.ok and res.failed > 0 and not res.canary_hit  # replaced by built-in wording, never shown


@pytest.mark.parametrize("case", runner.load_cases("oversize"), ids=lambda c: c["id"])
def test_oversize_requests_get_a_usable_message(case, work, actors, owner_conn, monkeypatch):
    calls: list = []
    enable_key(monkeypatch, AI_MAX_INPUT_TOKENS=case["max_input_tokens"])
    monkeypatch.setattr(ai, "_call_model", lambda *a, **k: calls.append(1) or "{}")
    res = runner.run_case(case, work, drain, owner_conn, actors)
    assert res.ok, res.problems
    assert not calls  # refused before any provider call


@pytest.mark.parametrize("case", runner.load_cases("provider_failure"), ids=lambda c: c["id"])
def test_provider_failures_still_produce_a_report(case, work, actors, owner_conn, monkeypatch):
    enable_key(monkeypatch)

    def failing(system, user, cfg=None):
        f = case["failure"]
        if f == "timeout":
            raise TimeoutError("timed out")
        if f == "http_5xx":
            raise RuntimeError("anthropic API returned 503: overloaded")
        if f == "malformed":
            return "I am sorry, here is some prose instead of JSON"
        return json.dumps({"items": []}) if "ITEMS" in user else json.dumps({"title": "x", "sections": []})

    if case["failure"] == "breaker_open":
        for _ in range(5):
            breaker.record(False)
        monkeypatch.setattr(ai, "_call_model", lambda *a, **k: pytest.fail("model called while the breaker is open"))
    else:
        monkeypatch.setattr(ai, "_call_model", failing)
    res = runner.run_case(case, work, drain, owner_conn, actors)
    assert res.ok, res.problems
    assert res.builtin  # built-in wording, within the same attempt where possible


def test_question_runner_with_an_oracle_model(work, monkeypatch):
    """The question harness itself: a stand-in model that calls the right tool and answers from its result passes the cases it should, and the
    runner flags a scope leak when an answer mentions what the asker may not see."""
    import re as _re

    from .test_assistant import script

    cases = {c["id"]: c for c in runner.load_cases("question")}
    actors = runner.actors_for(work)
    script(monkeypatch, [{"action": "tool", "tool": "get_overdue_and_blocked", "args_json": "{}"},
                         {"action": "answer", "sentences": ["“Write docs” is 3 days overdue.", "“Fix pipeline” is blocked."]}])
    ok = runner.run_question(cases["q-1"], work, actors)  # "What is overdue?" as admin: expects Write docs
    assert ok.ok and ok.checked == 2 and ok.failed == 0
    script(monkeypatch, [{"action": "tool", "tool": "get_overdue_and_blocked", "args_json": "{}"}, {"action": "answer", "sentences": ["“Write docs” is 3 days overdue."]}])
    leaked = runner.run_question({**cases["q-1"], "forbid": [_re.escape("Write docs")]}, work, actors)
    assert leaked.leak and not leaked.ok
    s = runner.summarise([ok, leaked])
    assert s["scope_leakage"] == 1 and s["question_pass_rate"] == 0.5 and s["answer_grounding_rate"] == 1.0 and runner.breaches(s)
