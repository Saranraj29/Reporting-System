"""The harness around the model (Phase 0): structured output + one repair, grounding verifier, redaction, versioned prompts, call records."""

import json
import re
import sys
import types

import pytest

from app.ai import gateway, prompts, redact, schemas, verify
from app.services import ai

from .conftest import drain
from .test_ai_reports import PLAN, create, fake_llm, window

CFG = ai.LLMConfig("openai", "m", "k")


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.text = payload, status, ""

    def json(self):
        return self._p


# ------------------------------------------------------------------ gateway
def test_gateway_passes_schema_and_temperature_zero(monkeypatch):
    seen = {}

    def fake(system, user, cfg):
        seen.update(schema=cfg.json_schema, temp=cfg.temperature, name=cfg.schema_name)
        return json.dumps({"items": [{"key": "a", "text": "x"}]})

    monkeypatch.setattr(ai, "_call_model", fake)
    out, info = gateway.call_structured("S", "U", schemas.NarrativeOut, schemas.NARRATIVE_SCHEMA, "report_text", CFG, "write_v1")
    assert out.items[0].key == "a" and not info.repaired and info.prompt_version == "write_v1"
    assert seen["schema"] is schemas.NARRATIVE_SCHEMA and seen["temp"] == 0.0 and seen["name"] == "report_text"


def test_exactly_one_repair_then_success(monkeypatch):
    prompts_seen = []
    replies = iter(["Sure! Here is your report.", json.dumps({"items": [{"key": "a", "text": "x"}]})])

    def fake(system, user, cfg):
        prompts_seen.append(user)
        return next(replies)

    monkeypatch.setattr(ai, "_call_model", fake)
    out, info = gateway.call_structured("S", "U", schemas.NarrativeOut, schemas.NARRATIVE_SCHEMA, "t", CFG, "v")
    assert out.items[0].text == "x" and info.repaired and len(prompts_seen) == 2
    assert "not valid" in prompts_seen[1] and prompts_seen[1].startswith("U")


def test_second_invalid_answer_raises_structural_error(monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "_call_model", lambda s, u, c: calls.append(1) or '{"items": "nope"}')
    with pytest.raises(gateway.StructuralError):
        gateway.call_structured("S", "U", schemas.NarrativeOut, schemas.NARRATIVE_SCHEMA, "t", CFG, "v")
    assert len(calls) == 2  # one call + one repair, never more


def test_provider_errors_are_not_swallowed(monkeypatch):
    def boom(s, u, c):
        raise RuntimeError("openai API returned 503")

    monkeypatch.setattr(ai, "_call_model", boom)
    with pytest.raises(RuntimeError):  # the job queue retries these
        gateway.call_structured("S", "U", schemas.NarrativeOut, schemas.NARRATIVE_SCHEMA, "t", CFG, "v")


def test_openai_wire_format_is_strict_json_schema(monkeypatch):
    seen = {}

    def post(url, headers=None, json=None, timeout=None):
        seen.update(body=json)
        return FakeResp({"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 120, "completion_tokens": 30, "prompt_tokens_details": {"cached_tokens": 100}}})

    monkeypatch.setattr(ai.httpx, "post", post)
    import dataclasses

    ai._call_model("S", "U", dataclasses.replace(CFG, json_schema=schemas.OUTLINE_SCHEMA, schema_name="report_structure", temperature=0.0))
    b = seen["body"]
    assert b["temperature"] == 0.0 and b["response_format"]["type"] == "json_schema"
    assert b["response_format"]["json_schema"]["strict"] is True and b["response_format"]["json_schema"]["name"] == "report_structure"
    assert ai.LAST_USAGE.get() == {"input": 120, "output": 30, "cached": 100}


def test_gemini_schema_is_converted(monkeypatch):
    seen = {}

    def post(url, headers=None, json=None, timeout=None):
        seen.update(body=json)
        return FakeResp({"candidates": [{"content": {"parts": [{"text": "{}"}]}}], "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}})

    monkeypatch.setattr(ai.httpx, "post", post)
    import dataclasses

    ai._call_model("S", "U", dataclasses.replace(ai.LLMConfig("gemini", "g", "k"), json_schema=schemas.OUTLINE_SCHEMA, temperature=0.0))
    gen = seen["body"]["generationConfig"]
    flat = json.dumps(gen["responseSchema"])
    assert "additionalProperties" not in flat and '"nullable": true' in flat and '"null"' not in flat
    assert gen["temperature"] == 0.0 and ai.LAST_USAGE.get()["input"] == 7


def test_anthropic_uses_forced_tool_use(monkeypatch):
    seen = {}

    class Block:
        type, input = "tool_use", {"items": []}

    class Client:
        def __init__(self, **kw):
            self.messages = self

        def create(self, **kw):
            seen.update(kw)
            return types.SimpleNamespace(content=[Block()], usage=types.SimpleNamespace(input_tokens=50, output_tokens=5, cache_read_input_tokens=40))

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Client))
    import dataclasses

    out = ai._call_model("S", "U", dataclasses.replace(ai.LLMConfig("anthropic", "c", "k"), json_schema=schemas.NARRATIVE_SCHEMA, schema_name="report_text", temperature=0.0))
    assert json.loads(out) == {"items": []}
    assert seen["tool_choice"] == {"type": "tool", "name": "report_text"} and seen["temperature"] == 0.0
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}  # the static prompt is cached
    assert ai.LAST_USAGE.get() == {"input": 50, "output": 5, "cached": 40}


def test_prompts_are_versioned_files():
    p = prompts.load("plan_v1", CATALOG="- x (overall): y")
    assert p.id == "plan_v1" and "- x (overall): y" in p.text and "{{" not in p.text
    from app.services.airep import writer

    assert writer.PLAN_VERSION == "plan_v1" and writer.WRITE_VERSION == "write_v1" and "status_pie" in writer.PLAN_SYSTEM


# ------------------------------------------------------------------ redaction
@pytest.mark.parametrize("raw,clean", [
    ("Mail ravi.k@acme.com about it", "Mail [email] about it"),
    ("Ping @ravi on slack", "Ping [handle] on slack"),
    ("Call +91 98765 43210 today", "Call [phone] today"),
    ("See https://x.example.com/doc?token=abc123&u=1 now", "See [link] now"),
    ("Due 2026-11-04, 52.5 hours, 28% done", "Due 2026-11-04, 52.5 hours, 28% done"),  # dates and figures stay
    ("Plain https://example.com/docs link", "Plain https://example.com/docs link"),
])
def test_scrub(raw, clean):
    assert redact.scrub(raw) == clean


def test_llm_view_codes_people_and_scrubs_titles():
    facts = {"projects": [{"id": "1", "name": "Apollo", "owners": ["Mia Member"], "people": [{"name": "Max Member", "hours": 2}],
                           "activities": ["Mail Mia Member at mia@acme.com", "Call 98765 43210 now"]}], "company": "Acme", "period": {"start": "2026-11-01", "end": "2026-11-04"}}
    view, back = redact.llm_view(facts)
    dumped = json.dumps(view)
    assert "Mia" not in dumped and "Max" not in dumped and "@" not in dumped and "98765" not in dumped
    assert "Person A" in dumped and "[email]" in dumped and "[phone]" in dumped and set(back.values()) == {"Mia Member", "Max Member"}


# ------------------------------------------------------------------ verifier
VIEW = {
    "period": {"start": "2026-10-29", "end": "2026-11-04"},
    "totals": {"projects": 2, "planned": 18, "completed": 5, "in_progress": 9, "pending": 4, "hours": 52.5},
    "projects": [
        {"name": "Apollo", "progress": 39.6, "overdue": [{"title": "Write docs", "due_date": "2026-11-01", "days_late": 3}], "deliverables": ["Ship login"],
         "people": [{"name": "Person A", "hours": 9.75}]},
        {"name": "Hermes", "progress": 0, "blocked": ["Fix pipeline"]},
    ],
}
EV = verify.build_evidence(VIEW, {"Person A": "Mia"})

GOOD = [
    "Across 2 projects, 5 of 18 tasks were completed (28%); 52.5 hours were logged.",
    "Apollo is about 40% complete and “Write docs” is 3 days overdue.",
    "Person A logged 10 hours on “Ship login”.",
    "The period runs from 29 Oct to 4 Nov 2026 (2026-10-29 to 2026-11-04).",
    "13 tasks are still open.",
    "“Fix pipeline” is blocked in Hermes.",
]
BAD = [
    "Across 3 projects, 7 of 18 tasks were completed.",
    "Apollo is 75% complete.",
    "“Deploy the payment service” is late.",
    "Person Z fixed the pipeline.",
    "The release is due on 12 Dec.",
    "A total of 120 hours were logged.",
]


@pytest.mark.parametrize("text", GOOD)
def test_grounded_text_passes(text):
    res = verify.verify_text(text, EV, 2026)
    assert res.passed, res.flags


@pytest.mark.parametrize("text", BAD)
def test_ungrounded_text_fails(text):
    res = verify.verify_text(text, EV, 2026)
    assert not res.passed and res.flags


def test_verifier_precision_on_labelled_fixtures():
    good_pass = sum(verify.verify_text(t, EV, 2026).passed for t in GOOD) / len(GOOD)
    bad_pass = sum(verify.verify_text(t, EV, 2026).passed for t in BAD)
    assert good_pass >= 0.95 and bad_pass == 0  # no known-bad text passes


# ------------------------------------------------------------------ in the report flow
def test_ungrounded_section_falls_back_and_is_flagged(work, monkeypatch, owner_conn):
    def write(items):
        return {i["key"]: ("We completed 999 tasks and the team is thrilled." if i["key"] == "s1" else "- Ship it") for i in items}

    fake_llm(monkeypatch, plan=PLAN, write=write)
    rep = create(work.admin, work)
    work.admin.post(f"/ai-reports/{rep['id']}/approve")
    drain()
    done = work.admin.get(f"/ai-reports/{rep['id']}").json()
    assert done["status"] == "ready" and done["builtin_sections"] == 1 and done["missing_text"] is True
    md = work.admin.get(f"/ai-reports/{rep['id']}/markdown").text
    assert "999" not in md and "Ship it" in md  # the invented sentence never reaches the report
    row = owner_conn.execute("select model, prompt_version, usage, verification, latency_ms from ai_reports where id = %s", (rep["id"],)).fetchone()
    assert row[0] == "claude-sonnet-5-5" and row[1] == "write_v1" and row[4] is not None
    assert row[3]["failed"] and row[3]["failed"]["s1"][0]["check"] == "number"


def test_prose_answer_is_repaired_once_in_the_plan(work, monkeypatch):
    calls = []
    fake_llm(monkeypatch, plan=PLAN)
    real = ai._call_model

    def flaky(system, user, cfg=None):
        calls.append(user)
        return "Here is the structure you asked for" if len(calls) == 1 else real(system, user, cfg)

    monkeypatch.setattr(ai, "_call_model", flaky)
    rep = create(work.admin, work)
    assert rep["status"] == "outline_ready" and rep["written_by"] == "ai" and len(calls) == 2


def test_twice_invalid_plan_uses_builtin_in_the_same_attempt(work, monkeypatch, owner_conn):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(ai, "_call_model", lambda s, u, c=None: "no json here")
    r = work.admin.post("/ai-reports", {**window(work)})
    drain()
    job = owner_conn.execute("select status, attempts from jobs where kind = 'ai_report.plan'").fetchone()
    assert job == ("done", 1)  # one job attempt, no retry cycle
    rep = work.admin.get(f"/ai-reports/{r.json()['id']}").json()
    assert rep["status"] == "outline_ready" and rep["written_by"] == "builtin" and "unusable form" in rep["outline"]["notes"]


def test_titles_with_personal_data_are_scrubbed_before_the_model(work, monkeypatch):
    work.mgr.post("/tasks", {"project_id": work.project["id"], "title": "Email ravi.k@client.com or call 98765 43210", "assignee_ids": [work.m1.user_id]}).raise_for_status()
    seen: list = []
    fake_llm(monkeypatch, plan=PLAN, record=seen)
    rep = create(work.admin, work, request="Mail the CTO at cto@acme.com")
    work.admin.post(f"/ai-reports/{rep['id']}/approve")
    drain()
    assert seen and all("@" not in u and "98765" not in u for _, u in seen)
    assert any("[email]" in u for _, u in seen)
    assert not re.search(r"ravi\.k", json.dumps(seen))
