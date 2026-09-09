"""Gemini Flash article analysis  Step 1 of the Intelligent pipeline.

Given an article's title + body/excerpt, ask Gemini to *understand* it and
return structured metadata (category, manufacturer, product, device type,
targeted image-search queries, avoid-keywords, confidence) rather than a single
naive search string. That structure is what makes the downstream image search
accurate.

Runs on a dedicated key (`INTEL_gen_news_gemini`) against Google's
OpenAI-compatible Generative Language endpoint  the exact same wire shape the
project's LLM fallback already uses (see core/llm.py), just a different key and
a purpose-built prompt. Kept out of core.llm / credits.run_ai on purpose: this
is an internal editorial helper, it must never touch the customer credit wallet
and must never share the customer-facing AI budget.

Configuration is read lazily inside the call (never at import), so importing
this module is always safe even with no key set  an unconfigured call raises
`IntelNotConfigured`, which callers catch and treat as "no analysis available".
"""
import json
import os
import re

import requests
from django.conf import settings

REQUEST_TIMEOUT_SECONDS = 30

# The recommended category vocabulary from the spec  the analysis is asked to
# pick exactly one of these, which then selects the image-retrieval strategy.
CATEGORIES = [
    "Phone", "Tablet", "Laptop", "Desktop", "CPU", "GPU", "Motherboard",
    "RAM", "SSD", "Monitor", "Game", "Operating System", "AI", "Company",
    "Networking", "Cybersecurity", "Cloud", "Programming", "General Tech",
]


class IntelNotConfigured(Exception):
    """Raised when article analysis is attempted before the Gemini key is set."""


class IntelRequestFailed(Exception):
    """Raised when the analysis request or its JSON parse fails."""


def _config():
    return {
        "base_url": getattr(
            settings, "INTEL_GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ).rstrip("/"),
        "api_key": getattr(settings, "INTEL_GEMINI_API_KEY", "")
        or os.environ.get("INTEL_gen_news_gemini", ""),
        "model": getattr(settings, "INTEL_GEMINI_MODEL", "gemini-flash-latest"),
    }


def is_configured():
    return bool(_config()["api_key"])


_SYSTEM = (
    "You are a metadata-extraction engine for a technology news and hardware "
    "publication's image pipeline. You read an article and return ONLY a strict "
    "JSON object describing what the article is really about, so the backend can "
    "find an accurate photograph of the subject. You never invent a product that "
    "the article does not mention. If the article is about a company or an "
    "abstract topic with no single physical product, say so honestly and lower "
    "your confidence."
)


def _build_prompt(title, body, category_hint=None):
    hint = f"\nEditor's current category guess (may be wrong): {category_hint}" if category_hint else ""
    return f"""Analyse this article and extract structured metadata.

Title: {title}
Body / excerpt: {(body or '').strip()[:1500]}{hint}

Return ONLY this JSON object (no prose, no code fences):
{{
  "category": one of {CATEGORIES},
  "primary_subject": "the single main thing the article is about, in a few words",
  "manufacturer": "brand/company that makes the subject, or empty string",
  "product_name": "specific product/model name, or empty string",
  "device_type": "e.g. 'Laptop Processor', 'Graphics Card', 'Smartphone', or empty string",
  "search_query": "the best single image-search query for an official/product photo of the subject",
  "alternative_queries": ["2-4 alternative image-search queries, most-specific first"],
  "avoid_keywords": ["terms that would indicate a WRONG image (rival brands, wrong generations)"],
  "confidence": 0.0-1.0 how confident you are the subject is a real, photographable thing
}}

Rules:
- search_query should target an official product/press image where a product exists
  (e.g. "AMD Ryzen AI Max+ 395 official press image"), or a company HQ / logo for a
  company story, or a representative concept image for an abstract topic.
- Never put a competitor or a different generation in search_query.
- If the article names no concrete product, leave product_name empty and lower confidence."""


def analyze_article(title, body="", category_hint=None):
    """Return the structured metadata dict for an article.

    Raises IntelNotConfigured (no key) or IntelRequestFailed (HTTP/parse error).
    The returned dict always has every key present (missing/blank fields are
    normalised), so callers can index it without guarding each field.
    """
    config = _config()
    if not config["api_key"]:
        raise IntelNotConfigured("INTEL_gen_news_gemini is not set.")

    try:
        resp = requests.post(
            f"{config['base_url']}/chat/completions",
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": config["model"],
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _build_prompt(title, body, category_hint)},
                ],
                # Headroom: current Gemini flash models spend part of the output
                # budget on internal reasoning before the visible JSON, and the
                # OpenAI-compat layer rejects the thinking-disable params  too
                # small a cap comes back with empty content (finish_reason=length).
                "max_tokens": 1200,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise IntelRequestFailed(f"gemini analysis: {exc}")

    return _parse(content, fallback_title=title, fallback_category=category_hint)


def _parse(content, fallback_title="", fallback_category=None):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE).strip()
    # Models occasionally wrap the object in leading prose  grab the first {...}.
    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        raise IntelRequestFailed("analysis response contained no JSON object")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise IntelRequestFailed(f"analysis JSON parse: {exc}")

    def _str(key):
        return str(data.get(key, "") or "").strip()

    def _list(key):
        val = data.get(key, [])
        if isinstance(val, str):
            val = [val]
        return [str(v).strip() for v in val if str(v).strip()] if isinstance(val, list) else []

    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    category = _str("category") or (fallback_category or "General Tech")
    search_query = _str("search_query") or _str("primary_subject") or fallback_title

    return {
        "category": category,
        "primary_subject": _str("primary_subject") or fallback_title,
        "manufacturer": _str("manufacturer"),
        "product_name": _str("product_name"),
        "device_type": _str("device_type"),
        "search_query": search_query,
        "alternative_queries": _list("alternative_queries"),
        "avoid_keywords": _list("avoid_keywords"),
        "confidence": confidence,
    }
