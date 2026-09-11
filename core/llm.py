"""Shared, provider-agnostic LLM client for every premium AI tool.

Default provider is Groq; Gemini (or anything else OpenAI-compatible) is the fallback.
Swapping providers is a pure env-var change  no code here should ever hard-code
"groq" or "gemini".

Deliberate deviation from the spec's scaffold: the spec's sample reads
`os.environ["LLM_BASE_URL"]` at *import time*, which would crash Django on startup
the moment anything imports this module  and during Phase 2 no real LLM keys are
configured yet (no gateway is approved, see the handoff doc). Config is read lazily,
inside `llm_complete()`, so importing this module is always safe; only an actual
completion attempt without configured keys raises (and that error is caught by
`get_completion` and surfaced as a normal "not available" result).

Also deviates from the spec by using `requests` instead of the `openai` SDK: this
project has no isolated virtualenv (packages install into the shared system/conda
environment), and Groq/Gemini's OpenAI-compatible endpoints are a single plain POST,
so the SDK isn't worth the extra footprint. Same interface, zero new global deps.
"""
import hashlib
import json
import os
import re

import requests
from django.core.cache import cache

DEFAULT_MODEL = "groq/compound-mini"
DEFAULT_FALLBACK_MODEL = "gemini-2.0-flash"
REQUEST_TIMEOUT_SECONDS = 30
# Claude runs are slower than the Groq/Gemini path but must still finish under
# the 120s Celery hard limit; give it a longer, dedicated timeout.
CLAUDE_TIMEOUT_SECONDS = 60
CLAUDE_ANTHROPIC_VERSION = "2023-06-01"
CACHE_TTL_SECONDS = 60 * 60 * 24 * 7  # a week  identical prompts are genuinely identical

# Rough published per-token pricing (USD), used only to estimate est_cost_usd for the
# quota/budget guardrails. Not billing-grade precision  update as pricing changes or
# as real provider usage dashboards become available.
PRICING_USD_PER_1K_TOKENS = {
    "llama-3.1-8b-instant": {"in": 0.00005, "out": 0.00008},
    "llama-3.1-70b-versatile": {"in": 0.00059, "out": 0.00079},
    "gemini-1.5-flash": {"in": 0.000075, "out": 0.0003},
    "gemini-2.0-flash": {"in": 0.0001, "out": 0.0004},
    "claude-sonnet-5": {"in": 0.003, "out": 0.015},
}
FALLBACK_PRICE_PER_1K = {"in": 0.0005, "out": 0.0015}  # used for unrecognized models


class LLMNotConfigured(Exception):
    """Raised when a completion is attempted before LLM_API_KEY (or the fallback) is set."""


class LLMRequestFailed(Exception):
    """Raised when both the primary and fallback provider calls fail."""


def _provider_config(fallback=False):
    if fallback:
        return {
            "base_url": os.environ.get("LLM_FALLBACK_BASE_URL", ""),
            "api_key": os.environ.get("LLM_FALLBACK_API_KEY", ""),
            "model": os.environ.get("LLM_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL),
        }
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        "api_key": os.environ.get("LLM_API_KEY", ""),
        "model": os.environ.get("LLM_MODEL", DEFAULT_MODEL),
    }


def _call_provider(system, user_msg, max_tokens, fallback=False):
    config = _provider_config(fallback=fallback)
    if not config["api_key"]:
        raise LLMNotConfigured(
            f"{'LLM_FALLBACK_API_KEY' if fallback else 'LLM_API_KEY'} is not set."
        )

    resp = requests.post(
        f"{config['base_url'].rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
        json={
            "model": config["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": max_tokens,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    # Strip <think>...</think> blocks emitted by reasoning models (e.g. qwen3)
    # before the actual response. These break every downstream JSON parser.
    # Strip <think>...</think> blocks emitted by reasoning models (e.g. qwen3).
    # Some models put their JSON *after* the block; others embed it inside.
    # Strategy: if a </think> tag exists, take everything after the last one.
    # If stripping leaves nothing, fall back to regex-strip (content was inside the block).
    if "</think>" in content:
        after_think = content.split("</think>")[-1].strip()
        content = after_think if after_think else re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    content = content.strip()
    usage = data.get("usage", {})
    tokens_in = usage.get("prompt_tokens", 0)
    tokens_out = usage.get("completion_tokens", 0)
    return content, tokens_in, tokens_out, config["model"]


def llm_complete(system, user_msg, max_tokens=800):
    """Try the primary provider (Groq by default); fall back to the secondary
    (Gemini by default) if the primary errors or isn't configured.

    Returns (content, tokens_in, tokens_out, model_used).
    Raises LLMNotConfigured if neither provider has an API key set.
    Raises LLMRequestFailed if both are configured but both requests fail.
    """
    primary_configured = bool(_provider_config(fallback=False)["api_key"])
    fallback_configured = bool(_provider_config(fallback=True)["api_key"])

    if not primary_configured and not fallback_configured:
        raise LLMNotConfigured("Neither LLM_API_KEY nor LLM_FALLBACK_API_KEY is set.")

    errors = []
    if primary_configured:
        try:
            return _call_provider(system, user_msg, max_tokens, fallback=False)
        except Exception as exc:  # noqa: BLE001  genuinely want to try the fallback on any failure
            print(f"[llm_complete] primary provider failed ({_provider_config(fallback=False)['model']}): {exc}")
            errors.append(f"primary: {exc}")

    if fallback_configured:
        try:
            return _call_provider(system, user_msg, max_tokens, fallback=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[llm_complete] fallback provider failed ({_provider_config(fallback=True)['model']}): {exc}")
            errors.append(f"fallback: {exc}")

    raise LLMRequestFailed("; ".join(errors))


def estimate_cost_usd(model, tokens_in, tokens_out):
    prices = PRICING_USD_PER_1K_TOKENS.get(model, FALLBACK_PRICE_PER_1K)
    return (tokens_in / 1000) * prices["in"] + (tokens_out / 1000) * prices["out"]


def cache_key_for(tool, model, system, user_msg):
    normalized = f"{tool}|{model}|{system.strip()}|{user_msg.strip()}"
    return "llm:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_completion(tool, system, user_msg, max_tokens=800):
    """The full wrap: cache → llm_complete → cache write.

    Deliberately does NOT check quota/budget itself  callers (premium views) do that
    first via core.quota, since the appropriate error response differs per view
    (JSON for an API endpoint, an HTML banner for a page, etc). This function is only
    reached once a caller has already confirmed the request is allowed.

    Returns a dict: {content, tokens_in, tokens_out, est_cost_usd, cache_hit, model}.
    """
    probe_model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    key = cache_key_for(tool, probe_model, system, user_msg)
    cached = cache.get(key)
    if cached is not None:
        result = json.loads(cached)
        result["cache_hit"] = True
        result["est_cost_usd"] = 0
        return result

    content, tokens_in, tokens_out, model_used = llm_complete(system, user_msg, max_tokens=max_tokens)
    est_cost = estimate_cost_usd(model_used, tokens_in, tokens_out)

    result = {
        "content": content,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model": model_used,
        "cache_hit": False,
        "est_cost_usd": est_cost,
    }
    cache.set(key, json.dumps({**result, "cache_hit": False}), timeout=CACHE_TTL_SECONDS)
    return result


def claude_complete(system, user_msg, max_tokens):
    """Single Claude (Anthropic Messages API) call  the only paid model in the
    product. Kept separate from llm_complete() on purpose:

    - No provider fallback. A failed Claude call must never silently downgrade to
      a free model or bill the user for nothing  it raises LLMRequestFailed and
      the caller (credits.services.run_ai) surfaces a 502 having charged nothing.
    - No Redis response cache. A cache hit would make "was I charged?" ambiguous;
      Claude spend is always metered against a real API call.
    - Thinking is disabled so credit charges stay predictable and bounded by the
      per-operation MAX_OUTPUT_TOKENS cap (thinking tokens would inflate the bill
      invisibly). Sampling params are omitted  Sonnet 5 rejects non-defaults.
    - Prompt caching is enabled on the system block (~90% off cached input); the
      returned tokens_in folds in cache-creation/read tokens so the credit charge
      reflects real input processed.

    Uses plain `requests` for the same reason the rest of this module does (see the
    module docstring): no isolated virtualenv, one plain POST, no extra global dep.

    Returns (content, tokens_in, tokens_out, model_used).
    Raises LLMNotConfigured if ANTHROPIC_API_KEY is unset; LLMRequestFailed on any
    request/HTTP/parse error.
    """
    from django.conf import settings

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LLMNotConfigured("ANTHROPIC_API_KEY is not set.")

    base_url = getattr(settings, "ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    model = getattr(settings, "CLAUDE_MODEL", "claude-sonnet-5")

    try:
        resp = requests.post(
            f"{base_url}/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": CLAUDE_ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "thinking": {"type": "disabled"},
                "system": [
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                ],
                "messages": [{"role": "user", "content": user_msg}],
            },
            timeout=CLAUDE_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        content = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        usage = data.get("usage", {})
        tokens_in = (
            usage.get("input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
        )
        tokens_out = usage.get("output_tokens", 0)
        return content, tokens_in, tokens_out, model
    except LLMNotConfigured:
        raise
    except Exception as exc:  # noqa: BLE001  any failure is a clean, chargeless 502
        raise LLMRequestFailed(f"claude: {exc}")
