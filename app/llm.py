"""LLM providers (free tiers): Google Gemini and Groq, switchable at runtime.

Both are called over plain HTTPS with httpx; no vendor SDK required.
Keys come from environment variables only and never reach the browser.

Model names change often on free tiers, so each provider has a fallback
chain: the model set in .env is tried first, then the defaults below. If a
model is retired (404/400 "not found"/"decommissioned"), the next one is used
and remembered for the rest of the process.
"""
from __future__ import annotations

import os
import time

import httpx

PROVIDERS = {
    "gemini": {
        "label": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "env_model": "GEMINI_MODEL",
        # "gemini-flash-latest" is Google's rolling alias for the current Flash model.
        "fallbacks": ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
        "key_url": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq",
        "env_key": "GROQ_API_KEY",
        "env_model": "GROQ_MODEL",
        # Groq retired llama-3.3-70b-versatile and llama-3.1-8b-instant on 16 Aug 2026.
        "fallbacks": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
        "key_url": "https://console.groq.com/keys",
    },
    "offline": {"label": "Offline (scripted)", "env_key": None, "env_model": None, "fallbacks": [], "key_url": None},
}
TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "25"))
_working_model: dict = {}  # provider -> model that last succeeded


class LLMError(Exception):
    pass


class _ModelGone(Exception):
    pass


def candidates(provider: str) -> list:
    p = PROVIDERS[provider]
    chain = []
    for m in [_working_model.get(provider), os.getenv(p["env_model"] or "", "").strip(), *p["fallbacks"]]:
        if m and m not in chain:
            chain.append(m)
    return chain


def model_for(provider: str) -> str:
    c = candidates(provider) if provider != "offline" else []
    return c[0] if c else ""


def is_configured(provider: str) -> bool:
    p = PROVIDERS.get(provider)
    return bool(p and (p["env_key"] is None or os.getenv(p["env_key"], "").strip()))


def status() -> dict:
    return {k: {"label": v["label"], "configured": is_configured(k), "model": model_for(k), "key_url": v["key_url"]}
            for k, v in PROVIDERS.items()}


def default_provider() -> str:
    pref = os.getenv("LLM_PROVIDER", "gemini")
    if pref in PROVIDERS and is_configured(pref):
        return pref
    for k in ("gemini", "groq"):
        if is_configured(k):
            return k
    return "offline"


def _gone(r: httpx.Response) -> bool:
    if r.status_code == 404:
        return True
    if r.status_code == 400:
        t = r.text.lower()
        return any(w in t for w in ("not found", "decommissioned", "deprecated", "does not exist", "not supported"))
    return False


async def _gemini(client, key, model, system, user) -> str:
    r = await client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            # Generous limit: newer Flash models may spend tokens thinking before answering.
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
        },
    )
    if _gone(r):
        raise _ModelGone(model)
    r.raise_for_status()
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "no answer")
        raise LLMError(f"Google Gemini returned no answer ({reason})")
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not text:
        raise LLMError("Google Gemini returned an empty answer")
    return text


async def _groq(client, key, model, system, user) -> str:
    body = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 1500,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"  # keep latency low; the answer is an explanation, not a puzzle
    r = await client.post("https://api.groq.com/openai/v1/chat/completions",
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=body)
    if _gone(r):
        raise _ModelGone(model)
    r.raise_for_status()
    text = (r.json()["choices"][0]["message"].get("content") or "").strip()
    if not text:
        raise LLMError("Groq returned an empty answer")
    return text


async def complete(provider: str, system: str, user: str) -> str:
    if provider == "offline":
        raise LLMError("Offline mode")
    if provider not in PROVIDERS:
        raise LLMError("Unknown provider")
    label = PROVIDERS[provider]["label"]
    if not is_configured(provider):
        raise LLMError(f"{label} API key is not set")
    key = os.getenv(PROVIDERS[provider]["env_key"], "").strip()
    call = _gemini if provider == "gemini" else _groq
    tried = []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for model in candidates(provider):
            try:
                text = await call(client, key, model, system, user)
                _working_model[provider] = model
                return text
            except _ModelGone:
                tried.append(model)
                if _working_model.get(provider) == model:
                    _working_model.pop(provider, None)
                continue
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                hint = {401: "API key rejected", 403: "API key not allowed for this model or region",
                        429: "free-tier rate limit reached, try again in a minute"}.get(code, f"HTTP {code}")
                raise LLMError(f"{label}: {hint}") from e
            except httpx.TimeoutException as e:
                raise LLMError(f"{label} timed out") from e
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
                raise LLMError(f"{label} request failed") from e
    raise LLMError(f"{label}: none of these models are available: {', '.join(tried)}. Set {PROVIDERS[provider]['env_model']} in .env")


async def test_provider(provider: str) -> dict:
    """Small live call used by the 'Test AI connection' button."""
    start = time.perf_counter()
    try:
        text = await complete(provider, "Reply with exactly: OK", "Connection test")
        ok = True
        detail = f"Connected using {_working_model.get(provider, model_for(provider))}"
        if "ok" not in text.lower():
            detail += f" (replied: {text[:40]})"
    except LLMError as e:
        ok, detail = False, str(e)
    return {"provider": provider, "label": PROVIDERS[provider]["label"], "ok": ok, "detail": detail,
            "ms": int((time.perf_counter() - start) * 1000)}
