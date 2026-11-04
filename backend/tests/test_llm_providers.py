"""The LLM behind report drafting is pluggable: Anthropic, OpenAI (or any OpenAI-compatible endpoint) and Gemini,
chosen per platform (env) or per company (Settings)."""

import json

import pytest

from app.config import get_settings
from app.security import encrypt
from app.services import ai

from .conftest import drain
from .test_client_reports import SECTIONS, make_template, window

REPLY = json.dumps({"sections": {s: f"LLM text for {s}" for s in SECTIONS}, "questions": []})


class FakeResp:
    def __init__(self, payload=None, status=200, text=""):
        self._p, self.status_code, self.text = payload, status, text

    def json(self):
        return self._p


def env(monkeypatch, **kv):
    for k, v in kv.items():
        monkeypatch.setenv(k.upper(), v)
    get_settings.cache_clear()


class Company:  # stand-in for the ORM row
    def __init__(self, provider=None, model=None, key=None):
        self.ai_provider, self.ai_model, self.ai_api_key = provider, model, encrypt(key) if key else None


# ---------------------------------------------------------------------------------- resolution
def test_no_keys_means_no_llm():
    assert ai.resolve_config() is None


def test_auto_picks_first_configured_provider(monkeypatch):
    env(monkeypatch, gemini_api_key="g-key")
    assert ai.resolve_config().provider == "gemini"
    env(monkeypatch, openai_api_key="o-key")
    assert ai.resolve_config().provider == "openai"  # anthropic > openai > gemini, first with a key
    env(monkeypatch, anthropic_api_key="a-key")
    assert ai.resolve_config().provider == "anthropic"


def test_platform_provider_can_be_forced(monkeypatch):
    env(monkeypatch, anthropic_api_key="a", openai_api_key="o", ai_provider="openai", openai_model="gpt-x")
    cfg = ai.resolve_config()
    assert (cfg.provider, cfg.model, cfg.api_key) == ("openai", "gpt-x", "o")
    env(monkeypatch, ai_provider="none")
    assert ai.resolve_config() is None


def test_company_settings_override_the_platform(monkeypatch):
    env(monkeypatch, anthropic_api_key="platform-a")
    cfg = ai.resolve_config(Company("gemini", "gemini-custom", "company-g"))
    assert (cfg.provider, cfg.model, cfg.api_key) == ("gemini", "gemini-custom", "company-g")  # key is decrypted
    assert ai.resolve_config(Company("none")) is None  # a company can switch AI off
    assert ai.resolve_config(Company("openai")) is None  # chose OpenAI but no key anywhere
    env(monkeypatch, openai_api_key="platform-o")
    assert ai.resolve_config(Company("openai")).api_key == "platform-o"  # falls back to the platform key of that provider
    assert ai.resolve_config(Company(None)).provider == "anthropic"  # no override: platform default


# ---------------------------------------------------------------------------------- wire formats
def test_openai_request_and_response(monkeypatch):
    seen = {}

    def post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, body=json)
        return FakeResp({"choices": [{"message": {"content": REPLY}}]})

    monkeypatch.setattr(ai.httpx, "post", post)
    cfg = ai.LLMConfig("openai", "gpt-test", "sk-o", "https://llm.example.com/v1/")
    assert ai._call_model("SYS", "USER", cfg) == REPLY
    assert seen["url"] == "https://llm.example.com/v1/chat/completions"  # OpenAI-compatible base URL
    assert seen["headers"] == {"Authorization": "Bearer sk-o"}
    assert seen["body"]["model"] == "gpt-test" and seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]


def test_gemini_request_and_response(monkeypatch):
    seen = {}

    def post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, body=json)
        return FakeResp({"candidates": [{"content": {"parts": [{"text": REPLY[:10]}, {"text": REPLY[10:]}]}}]})

    monkeypatch.setattr(ai.httpx, "post", post)
    out = ai._call_model("SYS", "USER", ai.LLMConfig("gemini", "gemini-test", "g-key"))
    assert out == REPLY
    assert seen["url"].endswith("/models/gemini-test:generateContent")
    assert seen["headers"] == {"x-goog-api-key": "g-key"}  # key in a header, not in the URL
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert seen["body"]["contents"][0]["parts"][0]["text"] == "USER"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_provider_http_errors_never_leak_the_key(monkeypatch, provider):
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: FakeResp(status=401, text="Incorrect API key provided: SECRET-KEY-123"))
    with pytest.raises(RuntimeError) as e:
        ai._call_model("s", "u", ai.LLMConfig(provider, "m", "SECRET-KEY-123"))
    assert "401" in str(e.value) and "SECRET-KEY-123" not in str(e.value)


# ---------------------------------------------------------------------------------- end to end
def test_company_setting_drives_the_draft_and_the_key_stays_secret(work, monkeypatch, owner_conn):
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json))
        return FakeResp({"choices": [{"message": {"content": REPLY}}]})

    monkeypatch.setattr(ai.httpx, "post", post)
    saved = work.admin.patch("/settings", {"ai_provider": "openai", "ai_model": "gpt-company", "ai_api_key": "sk-company-secret"})
    assert saved.status_code == 200
    s = saved.json()["ai"]
    assert s["provider"] == "openai" and s["model"] == "gpt-company" and s["key_configured"] and s["effective_provider"] == "openai"
    assert "sk-company-secret" not in json.dumps(work.admin.get("/settings").json())  # the key is write-only
    stored = owner_conn.execute("SELECT ai_api_key FROM companies").fetchone()[0]
    assert stored and "sk-company-secret" not in stored  # encrypted at rest

    t = make_template(work)
    r = work.mgr.post(f"/report-templates/{t['id']}/generate", window(work))
    drain()
    run = work.mgr.get(f"/report-runs/{r.json()['id']}").json()
    assert run["status"] == "drafted" and run["ai_provider"] == "openai"
    assert run["ai_text"]["Summary"] == "LLM text for Summary"
    url, headers, body = calls[0]
    assert headers["Authorization"] == "Bearer sk-company-secret" and body["model"] == "gpt-company"
    user_prompt = body["messages"][1]["content"]
    for forbidden in ("Mia", "Max", "Olive", "Hermes", "people"):  # same privacy boundary for every provider
        assert forbidden not in user_prompt


def test_switching_a_company_back_to_default_or_off(work, monkeypatch):
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: pytest.fail("no LLM call expected"))
    work.admin.patch("/settings", {"ai_provider": "gemini", "ai_api_key": "g"}).raise_for_status()
    assert work.admin.get("/settings").json()["ai"]["effective_provider"] == "gemini"
    off = work.admin.patch("/settings", {"ai_provider": "none"}).json()["ai"]
    assert off["effective_provider"] == "figures_only"
    t = make_template(work)
    r = work.mgr.post(f"/report-templates/{t['id']}/generate", window(work))
    drain()
    assert work.mgr.get(f"/report-runs/{r.json()['id']}").json()["ai_provider"] == "figures_only"
    back = work.admin.patch("/settings", {"ai_provider": "default", "clear_ai_key": True}).json()["ai"]
    assert back["provider"] == "default" and not back["key_configured"]


def test_settings_validation_and_permissions(work):
    assert work.admin.patch("/settings", {"ai_provider": "skynet"}).status_code == 422
    assert work.mgr.patch("/settings", {"ai_provider": "openai"}).status_code == 403
    assert work.mgr.post("/settings/ai/test").status_code == 403


def test_connection_test_button(work, monkeypatch):
    r = work.admin.post("/settings/ai/test").json()
    assert r["ok"] is False and "No LLM is configured" in r["message"]
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: FakeResp({"choices": [{"message": {"content": '{"ok": true}'}}]}))
    r = work.admin.post("/settings/ai/test", {"provider": "openai", "api_key": "typed-in-form", "model": "gpt-q"}).json()
    assert r == {"ok": True, "provider": "openai", "model": "gpt-q", "message": 'openai replied: {"ok": true}'}  # works before saving
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: FakeResp(status=403, text="API key typed-in-form not allowed"))
    bad = work.admin.post("/settings/ai/test", {"provider": "gemini", "api_key": "typed-in-form"}).json()
    assert bad["ok"] is False and "403" in bad["message"] and "typed-in-form" not in bad["message"]
