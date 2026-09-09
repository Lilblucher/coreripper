"""The Intelligent image pipeline  ties analysis + retrieval + scoring together.

`resolve_article_image(title, body, category_hint)` runs the full flow:

    analyse (Gemini) -> build queries -> retrieve candidates ->
    score + confidence gate -> pick best (or None -> placeholder)

Returns an `ImageResult` (a plain dict, JSON-friendly for storing on a model)
or None when nothing clears the confidence threshold. Vision verification is a
documented future step (spec Step 7); until a vision model is wired, scoring is
a transparent heuristic: retrieval rank + resolution + a bonus when the
candidate's text corroborates the extracted product/manufacturer. Gemini's
analysis confidence is used to build better queries, not to penalise the image
score -- an abstract news topic should still get a good image if the search
returns one. No fabricated match scores.

Everything is defensive: if analysis is unconfigured or fails, the pipeline
still tries a best-effort search from the raw title so an article is never left
worse off than the old category-pool behaviour  it just skips the smart part.
"""
import hashlib

from django.conf import settings

from . import gemini, image_search

# Lowered from 0.60: the old value multiplied image relevance by Gemini's
# analysis confidence, so abstract news topics (confidence ~0.4) could never
# clear 0.60 even with a perfect image. 0.45 is the right gate for image
# relevance alone now that the two concerns are separated in _score_candidate.
DEFAULT_CONFIDENCE_THRESHOLD = 0.45
DEFAULT_CANDIDATE_LIMIT = 8


def _threshold():
    return float(getattr(settings, "INTEL_IMAGE_CONFIDENCE_THRESHOLD", DEFAULT_CONFIDENCE_THRESHOLD))


def source_hash(*parts):
    """Stable hash of the inputs that, when unchanged, mean regeneration is a
    no-op  the same change-gate idea the hardware AI profiles use."""
    joined = "\x01".join((p or "").strip() for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def build_queries(analysis):
    """Ordered, deduped query list from the analysis  primary first, then the
    model's alternatives, then a couple of deterministic templated fallbacks
    (spec Step 5) built from manufacturer + product."""
    queries = []

    def add(q):
        q = (q or "").strip()
        if q and q.lower() not in {x.lower() for x in queries}:
            queries.append(q)

    add(analysis.get("search_query"))
    for q in analysis.get("alternative_queries", []):
        add(q)

    manufacturer = analysis.get("manufacturer", "")
    product = analysis.get("product_name", "")
    subject = f"{manufacturer} {product}".strip() or analysis.get("primary_subject", "")
    if subject:
        add(f"{subject} official image")
        add(f"{subject} product photo")
        add(f"{subject} press image")
    return queries


def _score_candidate(candidate, analysis, rank, total):
    """Transparent heuristic 0-1. Higher = better. Not a vision match  see
    module docstring.

    Gemini's analysis.confidence is intentionally NOT applied here as a
    multiplier. It measures how well Gemini understood the article subject, not
    how relevant the candidate image is. Multiplying by it caused abstract news
    articles (confidence ~0.4) to never clear the threshold even when the image
    search returned a genuinely good result. Instead, confidence is used
    upstream (build_queries) to produce better search terms; the gate here
    judges the image candidate on its own merits.
    """
    # Retrieval rank: first result is most relevant to the engine.
    rank_score = 1.0 - (rank / max(total, 1)) * 0.5  # 1.0 .. 0.5

    # Resolution bonus (real product/press shots tend to be larger).
    px = candidate.get("width", 0) * candidate.get("height", 0)
    res_score = 0.0
    if px >= 1_000_000:
        res_score = 0.2
    elif px >= 250_000:
        res_score = 0.1

    # Corroboration: does the candidate's text mention the product/manufacturer?
    text = f"{candidate.get('title','')} {candidate.get('source_name','')} {candidate.get('url','')}".lower()
    corroboration = 0.0
    for token in (analysis.get("product_name", ""), analysis.get("manufacturer", "")):
        token = (token or "").strip().lower()
        if token and token in text:
            corroboration += 0.15

    # Small bonus when Gemini is highly confident about the subject: good
    # analysis means better queries, which means the top result is more likely
    # to be right. Cap at 0.1 so it can tip a borderline case but never
    # override a weak image match.
    analysis_bonus = min(0.1, analysis.get("confidence", 0.5) * 0.1)

    raw = rank_score + res_score + corroboration + analysis_bonus
    return min(1.0, raw)


def resolve_article_image(title, body="", category_hint=None):
    """Full pipeline. Returns an ImageResult dict or None.

    ImageResult keys: image_url, thumb_url, source_name, source_url,
    credit_name, credit_url, license_name, provider, confidence, search_query,
    alternative_queries, manufacturer, product_name, category, device_type."""
    # --- Step 1: analyse (best-effort; degrade gracefully). ---
    try:
        analysis = gemini.analyze_article(title, body, category_hint)
    except (gemini.IntelNotConfigured, gemini.IntelRequestFailed):
        analysis = {
            "category": category_hint or "General Tech",
            "primary_subject": title, "manufacturer": "", "product_name": "",
            "device_type": "", "search_query": title, "alternative_queries": [],
            "avoid_keywords": [], "confidence": 0.4,
        }

    # --- Steps 3-6: build queries, retrieve candidates. ---
    queries = build_queries(analysis)
    candidates = image_search.search_images(
        queries, avoid_keywords=analysis.get("avoid_keywords"),
        limit=DEFAULT_CANDIDATE_LIMIT,
    )
    if not candidates:
        return None

    # --- Steps 7-8: score + confidence gate. ---
    total = len(candidates)
    scored = [
        (_score_candidate(c, analysis, i, total), c)
        for i, c in enumerate(candidates)
    ]
    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best = scored[0]

    if best_score < _threshold():
        return None

    return {
        "image_url": best["url"],
        "thumb_url": best["thumb_url"],
        "source_name": best["source_name"],
        "source_url": best["source_url"],
        "credit_name": best["credit_name"],
        "credit_url": best["credit_url"],
        "license_name": best["license_name"],
        "provider": best["provider"],
        "confidence": round(best_score, 3),
        "search_query": analysis.get("search_query", ""),
        "alternative_queries": analysis.get("alternative_queries", []),
        "manufacturer": analysis.get("manufacturer", ""),
        "product_name": analysis.get("product_name", ""),
        "device_type": analysis.get("device_type", ""),
        "category": analysis.get("category", ""),
    }
