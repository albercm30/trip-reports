import json

import httpx
import pytest

from app.config import settings
from app.services import ai


@pytest.fixture
def groq(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "gsk_test")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings, "llm_model", "llama-3.3-70b-versatile")
    monkeypatch.setattr(ai, "_gone", set())
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)
    calls = []

    def install(answers):
        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append(dict(json))
            status, body = answers(json["model"], len(calls))
            return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)
        monkeypatch.setattr(ai.httpx, "post", fake_post)
        return calls
    return install


def ok(text):
    return 200, {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}}


def test_retired_model_in_settings_is_skipped(groq):
    calls = groq(lambda model, n: ok("hola"))
    assert ai.complete("x")[0] == "hola"
    assert calls[0]["model"] == "openai/gpt-oss-120b"
    assert calls[0]["reasoning_effort"] == "low" and calls[0]["include_reasoning"] is False


def test_falls_back_when_a_model_is_gone_or_busy(groq, monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "some/new-model")

    def answers(model, n):
        if model == "some/new-model":
            return 404, {"error": {"message": "The model `some/new-model` has been decommissioned", "code": "model_decommissioned"}}
        if model == "openai/gpt-oss-120b":
            return 429, {"error": {"message": "Rate limit reached"}}
        return ok('{"species": []}')

    calls = groq(answers)
    text, _, _ = ai.complete("x", json_mode=True)
    assert json.loads(text) == {"species": []}
    assert "some/new-model" in ai._gone and "some/new-model" not in ai.model_chain()
    assert calls[-1]["model"] == "openai/gpt-oss-20b"


def test_strips_thinking_and_retries_without_json_mode(groq):
    def answers(model, n):
        if n == 1:
            return 400, {"error": {"message": "response_format json_object is not supported"}}
        return ok("<think>hmm</think> Texto corregido.")
    calls = groq(answers)
    assert ai.complete("x", json_mode=True)[0] == "Texto corregido."
    assert "response_format" in calls[0] and "response_format" not in calls[1]


def test_all_busy_is_reported_as_rate_limited(groq):
    groq(lambda model, n: (429, {"error": {"message": "Rate limit reached"}}))
    with pytest.raises(ai.AIError) as e:
        ai.complete("x")
    assert e.value.code == "rate_limited"


def test_rejected_key_stops_trying(groq):
    calls = groq(lambda model, n: (401, {"error": {"message": "Invalid API Key"}}))
    with pytest.raises(ai.AIError):
        ai.complete("x")
    assert len(calls) == 1


def test_admin_ai_check(client, groq, monkeypatch):
    from .conftest import signup
    monkeypatch.setattr(settings, "admin_emails", ("owner@example.com",))
    groq(lambda model, n: ok('{"ok": true}'))
    signup(client)
    page = client.get("/app/admin?check_ai=1").text
    assert "openai/gpt-oss-120b" in page and "Working" in page


def test_free_draft_keeps_one_language():
    from types import SimpleNamespace
    from app.services import freedraft
    notes = "Salimos con el mar en calma y vimos un grupo de calderones muy cerca del barco, luego delfines mulares."
    s = [SimpleNamespace(name="Calderón tropical", sci="", star=True, sure=True, heard=False, count=20)]
    text = freedraft.day_draft(1, "", notes, s, "en")
    assert "species" not in text.lower() and "highlight" not in text.lower()
    assert freedraft.notes_lang(notes) == "es" and freedraft.notes_lang("we saw the whales and then dolphins") == "en"


def test_day_prompt_asks_for_one_language_and_a_summary():
    p = ai.day_prompt(n=1, date_s="", place="", notes="vimos calderones", species_lines="- Short-finned Pilot Whale",
                      lang="en", tone="warm", context="")
    assert "never mix languages" in p and "not a transcript" in p
