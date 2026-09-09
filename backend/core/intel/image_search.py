"""Candidate image retrieval  Steps 3-6 of the Intelligent pipeline.

A small provider seam so the retrieval backend is swappable without touching the
pipeline:

- `GoogleImageProvider`  Google Custom Search JSON API (`searchType=image`).
  This is the primary source the user chose for official press/product imagery.
  It needs BOTH an API key (`GOOGLE_IMAGE_SEARCH_KEY`, defaulting to the same
  `INTEL_gen_news_gemini` key the analysis step uses) AND a Programmable Search
  Engine id (`GOOGLE_CSE_ID`, the `cx`). With no `cx` configured the provider
  reports itself unconfigured and returns nothing  it never errors the run.

- `CommonsImageProvider`  Wikimedia Commons (core.commons_images). Always
  available (no key), every result is real and CC-licensed. Used as the
  automatic fallback until the `cx` is supplied, and whenever Google returns
  nothing.

`search_images()` tries the configured primary across the primary + alternative
queries, dedups, drops candidates whose text matches an avoid-keyword, and falls
back to Commons if the primary yields zero. Each candidate is a normalised dict:
url, thumb_url, source_name, source_url, credit_name, credit_url, license_name,
width, height, title, provider.

Honesty-first: a network failure or empty result is an empty list, never a
fabricated URL. Licensing note: Google-image results are arbitrary web images;
the caller records the source page so attribution can be shown, matching how the
rest of the site credits every image it displays.
"""
import os

import requests
from django.conf import settings

from core.commons_images import fetch_commons_images

REQUEST_TIMEOUT_SECONDS = 12
GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


def _norm(**kw):
    base = {
        "url": "", "thumb_url": "", "source_name": "", "source_url": "",
        "credit_name": "", "credit_url": "", "license_name": "",
        "width": 0, "height": 0, "title": "", "provider": "",
    }
    base.update(kw)
    base["thumb_url"] = base["thumb_url"] or base["url"]
    return base


# ------------------------------------------------------------ Google provider

def _google_config():
    return {
        "key": getattr(settings, "GOOGLE_IMAGE_SEARCH_KEY", "")
        or os.environ.get("GOOGLE_IMAGE_SEARCH_KEY", "")
        or getattr(settings, "INTEL_GEMINI_API_KEY", "")
        or os.environ.get("INTEL_gen_news_gemini", ""),
        "cx": getattr(settings, "GOOGLE_CSE_ID", "") or os.environ.get("GOOGLE_CSE_ID", ""),
    }


def google_configured():
    cfg = _google_config()
    return bool(cfg["key"] and cfg["cx"])


def _google_search(query, limit):
    cfg = _google_config()
    if not (cfg["key"] and cfg["cx"]):
        return []
    try:
        resp = requests.get(
            GOOGLE_CSE_ENDPOINT,
            params={
                "key": cfg["key"],
                "cx": cfg["cx"],
                "q": query,
                "searchType": "image",
                "num": min(max(limit, 1), 10),
                "safe": "active",
                "imgSize": "large",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except (requests.RequestException, ValueError):
        return []

    results = []
    for it in items:
        img = it.get("image", {}) or {}
        results.append(_norm(
            url=it.get("link", ""),
            thumb_url=img.get("thumbnailLink", ""),
            source_name=it.get("displayLink", ""),
            source_url=img.get("contextLink", "") or it.get("image", {}).get("contextLink", ""),
            credit_name=it.get("displayLink", ""),
            credit_url=img.get("contextLink", ""),
            license_name="",  # web image  licence unknown; source page is credited instead
            width=int(img.get("width", 0) or 0),
            height=int(img.get("height", 0) or 0),
            title=it.get("title", ""),
            provider="google",
        ))
    return [r for r in results if r["url"]]


# ----------------------------------------------------------- Commons provider

def _commons_search(query, limit):
    out = []
    for r in fetch_commons_images(query, limit=limit):
        out.append(_norm(
            url=r["image_url"],
            thumb_url=r["thumb_url"],
            source_name="Wikimedia Commons",
            source_url=r.get("credit_url", ""),
            credit_name=r.get("credit_name", ""),
            credit_url=r.get("credit_url", ""),
            license_name=r.get("license_name", ""),
            title=query,
            provider="commons",
        ))
    return out


# --------------------------------------------------------------- orchestration

def _dedup(candidates):
    seen, out = set(), []
    for c in candidates:
        key = c["url"]
        if key and key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _drop_avoided(candidates, avoid_keywords):
    if not avoid_keywords:
        return candidates
    lowered = [k.lower() for k in avoid_keywords if k]
    kept = []
    for c in candidates:
        haystack = f"{c['title']} {c['source_name']} {c['url']}".lower()
        if any(bad in haystack for bad in lowered):
            continue
        kept.append(c)
    return kept


def search_images(queries, avoid_keywords=None, limit=8):
    """Retrieve up to `limit` candidate images for a list of queries (primary
    first). Returns a deduped, avoid-keyword-filtered candidate list, possibly
    empty. Tries the configured web provider first; falls back to Commons."""
    queries = [q for q in (queries or []) if q]
    if not queries:
        return []

    primary = []
    if google_configured():
        for q in queries:
            primary.extend(_google_search(q, limit))
            if len({c["url"] for c in primary}) >= limit:
                break
    primary = _drop_avoided(_dedup(primary), avoid_keywords)

    if len(primary) >= 1:
        return primary[:limit]

    # Fallback: Wikimedia Commons on the same queries.
    commons = []
    for q in queries:
        commons.extend(_commons_search(q, limit))
        if len({c["url"] for c in commons}) >= limit:
            break
    commons = _drop_avoided(_dedup(commons), avoid_keywords)
    return commons[:limit]
