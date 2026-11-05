"""AI operations: breaker, kill switches, context budget, tracing, quotas, worker lanes, feedback, usage."""

import json
import logging

import pytest

from app.ai import budget, policy
from app.ai.breaker import Breaker, breaker
from app.services import ai

from .conftest import drain
from .test_ai_reports import PLAN, create, fake_llm, window


# ------------------------------------------------------------------ breaker
class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def test_breaker_opens_after_five_consecutive_failures_and_probes_every_30s():
    clock = Clock()
    b = Breaker(clock)
    for _ in range(4):
        b.record(False)
    assert not b.is_open and b.allow()
    b.record(False)
    assert b.is_open and not b.allow()  # calls are skipped: built-in wording at once
    clock.t += 31
    assert b.allow() and not b.allow()  # one probe, then closed to calls again
    b.record(False)  # probe failed: stays open
    assert b.is_open
    clock.t += 31
    assert b.allow()
    b.record(True)  # probe succeeded
    assert not b.is_open and b.allow()


def test_breaker_opens_on_error_rate():
    clock = Clock()
    b = Breaker(clock)
    for _ in range(18):
        b.record(True)
    b.record(False)
    b.record(True)
    assert not b.is_open  # 1 error in 20 = 5 %, not above
    b.record(False)
    b.record(True)
    b.record(False)
    assert b.is_open  # 3 errors in 23 > 5 %


def never_called(monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "_call_model", lambda *a, **k: calls.append(1) or pytest.fail("model must not be called"))
    return calls


def enable_key(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    get_settings.cache_clear()


def test_open_breaker_gives_builtin_output_without_a_model_call(work, monkeypatch):
    enable_key(monkeypatch)
    never_called(monkeypatch)
    for _ in range(5):
        breaker.record(False)
    rep = create(work.admin, work)
    assert rep["status"] == "outline_ready" and rep["written_by"] == "builtin"
    assert work.admin.get("/ai-reports/options").json()["ai_status"] == "provider_down"


# ------------------------------------------------------------------ kill switches
def test_company_switch_stops_model_calls_within_60_seconds(work, monkeypatch):
    fake_llm(monkeypatch, plan=PLAN)
    assert create(work.admin, work)["written_by"] == "ai"
    assert work.admin.patch("/settings", {"ai_enabled": False}).json()["ai_enabled"] is False
    # within the cache window the old value may still apply; after 60 s it is re-read without a restart
    real = policy.time.monotonic
    monkeypatch.setattr(policy.time, "monotonic", lambda: real() + 61)
    never_called(monkeypatch)
    rep = create(work.admin, work)
    assert rep["written_by"] == "builtin"
    opts = work.admin.get("/ai-reports/options").json()
    assert opts["ai_enabled"] is False and opts["ai_status"] == "off"
    assert work.admin.patch("/settings", {"ai_enabled": True}).json()["ai_enabled"] is True


def test_only_settings_admins_can_flip_the_switch(work):
    assert work.mgr.patch("/settings", {"ai_enabled": False}).status_code == 403


def test_platform_switch_overrides_everything(work, monkeypatch):
    from app.config import get_settings

    fake_llm(monkeypatch, plan=PLAN)
    monkeypatch.setenv("AI_ENABLED", "false")
    get_settings.cache_clear()
    never_called(monkeypatch)
    assert create(work.admin, work)["written_by"] == "builtin"


# ------------------------------------------------------------------ context budget
def test_cap_view_keeps_true_totals():
    view = {"projects": [{"activities": list(range(100)), "deliverables": list(range(30)), "overdue": [1], "upcoming": list(range(25))}]}
    p = budget.cap_view(view)["projects"][0]
    assert len(p["activities"]) == 40 and p["activities_total"] == 100
    assert len(p["deliverables"]) == 20 and p["deliverables_total"] == 30
    assert len(p["upcoming"]) == 20 and p["upcoming_total"] == 25
    assert "overdue_total" not in p


def test_oversized_request_is_refused_with_a_clear_message(work, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("AI_MAX_INPUT_TOKENS", "8100")  # leaves ~100 tokens for facts
    get_settings.cache_clear()
    enable_key(monkeypatch)
    calls: list = []
    monkeypatch.setattr(ai, "_call_model", lambda *a, **k: calls.append(1) or "{}")
    r = work.admin.post("/ai-reports", {**window(work)})
    drain()
    rep = work.admin.get(f"/ai-reports/{r.json()['id']}").json()
    assert rep["status"] == "failed" and "fewer projects or a shorter period" in rep["error"] and not calls


def test_gateway_refuses_before_calling_when_over_budget(monkeypatch):
    from app.ai import gateway, schemas
    from app.config import get_settings

    monkeypatch.setenv("AI_MAX_INPUT_TOKENS", "100")
    get_settings.cache_clear()
    calls = never_called(monkeypatch)
    with pytest.raises(budget.ContextLimitError):
        gateway.call_structured("S", "x" * 1000, schemas.NarrativeOut, schemas.NARRATIVE_SCHEMA, "t", ai.LLMConfig("openai", "m", "k"), "v")
    assert not calls


# ------------------------------------------------------------------ tracing
def test_one_ai_calls_row_per_model_call_without_text_or_names(work, monkeypatch, owner_conn, caplog):
    fake_llm(monkeypatch, plan=PLAN)
    inner = ai._call_model

    def with_usage(system, user, cfg=None):
        ai.LAST_USAGE.set({"input": 1200, "output": 150, "cached": 900})
        return inner(system, user, cfg)

    monkeypatch.setattr(ai, "_call_model", with_usage)
    with caplog.at_level(logging.INFO, logger="ai"):
        rep = create(work.admin, work)
        work.admin.post(f"/ai-reports/{rep['id']}/approve")
        drain()
    rows = owner_conn.execute("select surface, prompt_version, input_tokens, output_tokens, cached_tokens, verifier, fallback, error_code from ai_calls order by created_at").fetchall()
    assert [r[0] for r in rows] == ["report.plan", "report.write"]
    assert rows[0][1] == "plan_v1" and rows[1][1] == "write_v1" and rows[1][2:5] == (1200, 150, 900) and rows[1][7] is None
    assert rows[1][5]["failed"] == 0 and rows[1][5]["checked"] > 0  # counts only, never text
    dumped = json.dumps([list(map(str, r)) for r in rows])
    assert "Mia" not in dumped and "Apollo" not in dumped  # no names, no prompt text
    lines = [r.getMessage() for r in caplog.records if r.name == "ai"]
    assert len(lines) == 2 and all("@" not in line and "Mia" not in line for line in lines)


def test_provider_error_is_recorded(work, monkeypatch, owner_conn):
    fake_llm(monkeypatch, plan=RuntimeError("503 from provider"))
    r = work.admin.post("/ai-reports", {**window(work)})
    drain()
    codes = [row[0] for row in owner_conn.execute("select error_code from ai_calls").fetchall()]
    assert codes and set(codes) == {"provider_error"}
    assert work.admin.get(f"/ai-reports/{r.json()['id']}").json()["status"] in ("planning", "outline_ready")


def test_budget_alert_logged_once_at_80_percent(work, monkeypatch, caplog):
    from app.ai import trace
    from app.config import get_settings

    trace._alerted.clear()
    monkeypatch.setenv("AI_MONTHLY_TOKEN_BUDGET", "1000")
    get_settings.cache_clear()
    fake_llm(monkeypatch, plan=PLAN)
    inner = ai._call_model

    def with_usage(system, user, cfg=None):
        ai.LAST_USAGE.set({"input": 900, "output": 10, "cached": 0})
        return inner(system, user, cfg)

    monkeypatch.setattr(ai, "_call_model", with_usage)
    with caplog.at_level(logging.WARNING, logger="ai"):
        create(work.admin, work)
        create(work.admin, work)
    assert sum("ai_budget_alert" in r.getMessage() for r in caplog.records) == 1


# ------------------------------------------------------------------ quota and lanes
def test_daily_report_quota(work, owner_conn):
    owner_conn.execute("update companies set ai_daily_report_quota = 2")
    for _ in range(2):
        assert work.admin.post("/ai-reports", {**window(work)}).status_code == 202
    r = work.admin.post("/ai-reports", {**window(work)})
    assert r.status_code == 429 and r.json()["code"] == "quota.reports"
    owner_conn.execute("update companies set ai_daily_report_quota = 3")
    assert work.admin.post("/ai-reports", {**window(work)}).status_code == 202


def test_ai_jobs_run_on_their_own_lane(work, owner_conn):
    work.admin.post("/ai-reports", {**window(work)}).raise_for_status()
    lanes = dict(owner_conn.execute("select kind, queue from jobs where kind like 'ai_%%' or kind like 'mail%%' or kind like 'notify%%'").fetchall())
    assert lanes["ai_report.plan"] == "ai"
    from app.worker import run_pending

    run_pending(queue="default")
    assert owner_conn.execute("select status from jobs where kind = 'ai_report.plan'").fetchone()[0] == "queued"  # a default worker never takes it
    run_pending(queue="ai")
    assert owner_conn.execute("select status from jobs where kind = 'ai_report.plan'").fetchone()[0] == "done"


# ------------------------------------------------------------------ feedback and usage
def test_feedback_one_vote_per_person(work):
    rep = create(work.admin, work)
    assert work.admin.get(f"/ai-reports/{rep['id']}").json()["my_feedback"] is None
    assert work.admin.post(f"/ai-reports/{rep['id']}/feedback", {"rating": "down", "reason": "Missed the overdue task"}).status_code == 204
    assert work.admin.get(f"/ai-reports/{rep['id']}").json()["my_feedback"] == "down"
    work.admin.post(f"/ai-reports/{rep['id']}/feedback", {"rating": "up"})
    assert work.admin.get(f"/ai-reports/{rep['id']}").json()["my_feedback"] == "up"
    assert work.admin.post(f"/ai-reports/{rep['id']}/feedback", {"rating": "maybe"}).status_code == 422
    assert work.m1.post(f"/ai-reports/{rep['id']}/feedback", {"rating": "up"}).status_code == 403


def test_usage_page_data(work, monkeypatch):
    fake_llm(monkeypatch, plan=PLAN)
    rep = create(work.admin, work)
    work.admin.post(f"/ai-reports/{rep['id']}/approve")
    drain()
    work.admin.post(f"/ai-reports/{rep['id']}/feedback", {"rating": "down"})
    u = work.admin.get("/ai/usage").json()
    assert u["calls"] == 2 and u["errors"] == 0 and u["thumbs"] == {"up": 0, "down": 1} and u["status"] == "ready"
    assert u["grounding_pass_rate"] == 1.0 and u["fallback_rate"] == 0.0 and u["p95_latency_ms"] is not None
    assert u["quota"]["reports_per_day"] == 50
    assert work.mgr.get("/ai/usage").status_code == 403
