"""Provider plumbing without network: fallbacks, missing keys, offline mode."""
import asyncio

import pytest

pytest.importorskip("httpx")
from app import llm  # noqa: E402


def test_groq_defaults_skip_retired_llama(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    llm._working_model.clear()
    assert llm.candidates("groq")[0] == "openai/gpt-oss-120b"
    assert not any("llama-3.3" in m for m in llm.candidates("groq"))


def test_env_model_tried_first(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "my-model")
    llm._working_model.clear()
    assert llm.candidates("gemini")[0] == "my-model"


def test_falls_back_when_model_retired(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("GEMINI_MODEL", "retired-model")
    llm._working_model.clear()
    seen = []

    async def fake(client, key, model, system, user):
        seen.append(model)
        if model == "retired-model":
            raise llm._ModelGone(model)
        return "OK"

    monkeypatch.setattr(llm, "_gemini", fake)
    assert asyncio.run(llm.complete("gemini", "s", "u")) == "OK"
    assert seen[:2] == ["retired-model", "gemini-flash-latest"]
    assert llm._working_model["gemini"] == "gemini-flash-latest"


def test_missing_key_and_offline(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(llm.LLMError, match="not set"):
        asyncio.run(llm.complete("groq", "s", "u"))
    with pytest.raises(llm.LLMError):
        asyncio.run(llm.complete("offline", "s", "u"))
    r = asyncio.run(llm.test_provider("groq"))
    assert r["ok"] is False and "not set" in r["detail"]
