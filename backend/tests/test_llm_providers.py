"""The LLM behind report drafting is pluggable: Anthropic, OpenAI (or any OpenAI-compatible endpoint) and Gemini.
It is chosen by environment variables only; nothing about it is exposed in the UI or the API."""

import json

import pytest

from app.config import get_settings
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


def test_unknown_provider_or_missing_key_means_no_llm(monkeypatch):
    env(monkeypatch, ai_provider="skynet", openai_api_key="o")
    assert ai.resolve_config() is None
    env(monkeypatch, ai_provider="gemini")  # forced provider without its own key: no silent fallback to another provider
    assert ai.resolve_config() is None


def test_openai_base_url_is_only_used_for_openai(monkeypatch):
    env(monkeypatch, ai_provider="openai", openai_api_key="o", openai_base_url="https://llm.internal/v1")
    assert ai.resolve_config().base_url == "https://llm.internal/v1"
    env(monkeypatch, ai_provider="gemini", gemini_api_key="g")
    assert ai.resolve_config().base_url is None


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
def test_env_provider_drives_the_draft_with_the_same_privacy_boundary(work, monkeypatch):
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json))
        return FakeResp({"choices": [{"message": {"content": REPLY}}]})

    monkeypatch.setattr(ai.httpx, "post", post)
    env(monkeypatch, ai_provider="openai", openai_api_key="sk-env-secret", openai_model="gpt-env")
    t = make_template(work)
    r = work.mgr.post(f"/report-templates/{t['id']}/generate", window(work))
    drain()
    run = work.mgr.get(f"/report-runs/{r.json()['id']}").json()
    assert run["status"] == "drafted" and run["ai_provider"] == "openai"
    assert run["ai_text"]["Summary"] == "LLM text for Summary"
    url, headers, body = calls[0]
    assert headers["Authorization"] == "Bearer sk-env-secret" and body["model"] == "gpt-env"
    user_prompt = body["messages"][1]["content"]
    for forbidden in ("Mia", "Max", "Olive", "Hermes", "people"):
        assert forbidden not in user_prompt


def test_gemini_from_env_end_to_end(work, monkeypatch):
    seen = {}

    def post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers)
        return FakeResp({"candidates": [{"content": {"parts": [{"text": REPLY}]}}]})

    monkeypatch.setattr(ai.httpx, "post", post)
    env(monkeypatch, gemini_api_key="g-env", gemini_model="gemini-env")
    t = make_template(work)
    r = work.mgr.post(f"/report-templates/{t['id']}/generate", window(work))
    drain()
    run = work.mgr.get(f"/report-runs/{r.json()['id']}").json()
    assert run["ai_provider"] == "gemini" and seen["url"].endswith("gemini-env:generateContent") and seen["headers"]["x-goog-api-key"] == "g-env"


def test_provider_none_forces_figures_only_even_with_keys(work, monkeypatch):
    monkeypatch.setattr(ai.httpx, "post", lambda *a, **k: pytest.fail("no LLM call expected"))
    env(monkeypatch, ai_provider="none", openai_api_key="o", gemini_api_key="g")
    t = make_template(work)
    r = work.mgr.post(f"/report-templates/{t['id']}/generate", window(work))
    drain()
    assert work.mgr.get(f"/report-runs/{r.json()['id']}").json()["ai_provider"] == "figures_only"


def test_llm_choice_is_not_exposed_through_the_api_or_ui_settings(work, monkeypatch):
    env(monkeypatch, openai_api_key="sk-must-not-leak")
    s = work.admin.get("/settings").json()
    assert "ai" not in s and "sk-must-not-leak" not in json.dumps(s)
    assert work.admin.post("/settings/ai/test").status_code in (404, 405)  # the connection-test endpoint is gone
    patched = work.admin.patch("/settings", {"ai_provider": "gemini", "ai_api_key": "x"}).json()  # unknown fields are ignored
    assert "ai" not in patched
