"""The automatic article editor  keeps already-published content fresh.

A scheduled pass (one Celery task per content type, see each app's tasks.py)
walks published news / hardware / blog rows that are due for a refresh and, per
the user's spec, on each due article it:

  * re-fetches the primary source and change-gates on it (unchanged source =>
    cheap no-op, same idea as the hardware AI-profile regeneration),
  * regenerates the summary / body from the fresh source text (news + hardware;
    blog only when Post.auto_managed is set  hand-written posts keep their body),
  * refreshes the image via the Intelligent pipeline,
  * refreshes the SEO description,
  * updates the source list where the source moved/redirected,
  * logs a "What's New" timeline entry (news + hardware) so readers see it was
    refreshed and when.

Published-content policy: changes are AUTO-APPLIED to live rows and logged  a
deliberate, recorded exception to the human-moderation-on-first-publish rule
(the user chose "auto-apply, log it"). Everything is best-effort and honesty
first: a fetch failure, an AI failure, or a low-confidence image miss simply
leaves that part of the article unchanged; nothing is fabricated, and a run over
unchanged content makes no edits.
"""
import re

import requests
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from . import pipeline
from .generate import refresh_article_image

REQUEST_TIMEOUT_SECONDS = 12
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CoreRipperAutoEditor/1.0)"}
_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_HTML_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


# ----------------------------------------------------------- source fetching

def fetch_source_text(url, max_chars=2000):
    """Best-effort readable text from an article URL. Returns "" on any failure
    (paywall, dead link, non-HTML)  the caller treats that as 'no fresh source'
    and simply skips the text-regeneration half."""
    if not url:
        return ""
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        ctype = resp.headers.get("Content-Type", "")
        if "html" not in ctype and "xml" not in ctype and ctype:
            return ""
        html = resp.text
    except requests.RequestException:
        return ""

    body = re.search(r"<body[^>]*>(.*)</body>", html, re.S | re.I)
    html = body.group(1) if body else html
    text = _HTML_RE.sub(" ", _TAG_RE.sub(" ", html))
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_chars]


# --------------------------------------------------------------- AI rewrite

def ai_rewrite(title, source_text, category):
    """Regenerate {summary, body} from fresh source text via the free-model AI
    router (user=None => never Claude, never billed, same as news drafting).
    Returns None on any failure or empty source."""
    import json

    if not source_text:
        return None
    from credits.services import run_ai

    system = (
        "You are a technical news editor for a developer-focused tech knowledge "
        "hub. You rewrite an existing article from its updated source, in your "
        "own words, staying strictly factual. You never fabricate quotes, "
        "statistics, or attributions."
    )
    user_msg = f"""Refresh this article from its current source content.

Title: {title}
Category: {category}
Current source content: {source_text[:1600]}

Return ONLY a JSON object with:
- "summary": 1-2 sentence blurb for a card preview / SEO description.
- "body": 3-5 short paragraphs, original wording, factual, no fabricated quotes.

Respond with ONLY the JSON object."""

    try:
        result = run_ai(user=None, operation="news_draft", system=system, user_msg=user_msg)
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", result["content"].strip(), flags=re.MULTILINE).strip()
        match = re.search(r"\{.*\}", content, re.S)
        parsed = json.loads(match.group(0) if match else content)
    except Exception:  # noqa: BLE001
        return None

    def _as_text(v):
        if isinstance(v, list):
            return "\n\n".join(str(p).strip() for p in v if str(p).strip())
        return str(v or "").strip()

    summary, body = _as_text(parsed.get("summary")), _as_text(parsed.get("body"))
    if not summary or not body:
        return None
    return {"summary": summary, "body": body}


# ------------------------------------------------------------- due selection

def _min_age():
    return int(getattr(settings, "INTEL_AUTOEDIT_MIN_AGE_DAYS", 7))


def _max_per_run():
    return int(getattr(settings, "INTEL_AUTOEDIT_MAX_PER_RUN", 10))


def _due_queryset(model, published_filter):
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=_min_age())
    qs = model.objects.filter(**published_filter).filter(
        Q(intel_last_edited_at__isnull=True) | Q(intel_last_edited_at__lt=cutoff)
    )
    # nulls first, then oldest-edited first
    return qs.order_by("intel_last_edited_at")[: _max_per_run()]


# --------------------------------------------------------------- per-type refresh

def _primary_source(obj):
    src = obj.sources.filter(is_primary=True).first() or obj.sources.first()
    return src


def refresh_news_article(obj, force=False):
    """Refresh one published NewsDraft. Returns a dict of what changed."""
    changed = {"text": False, "image": False, "source": False}
    src = _primary_source(obj)
    source_url = src.url if src else ""

    source_text = fetch_source_text(source_url)
    new_hash = pipeline.source_hash(obj.title, source_text or obj.ai_draft_body, obj.category)
    unchanged = new_hash == obj.intel_source_hash and obj.intel_last_edited_at is not None
    if unchanged and not force:
        return None  # no-op: nothing moved since last edit

    # 1) Text + SEO description (only when we actually got fresh source text).
    rewrite = ai_rewrite(obj.title, source_text, obj.category)
    if rewrite:
        obj.ai_summary = rewrite["summary"]
        obj.ai_draft_body = rewrite["body"]
        changed["text"] = True

    # 2) Image.
    changed["image"] = refresh_article_image(
        obj, obj.title, obj.ai_summary or obj.ai_draft_body, obj.category, force=force, save=False
    )

    # 3) Source moved/redirected? Record the resolved final URL.
    if src and source_url:
        final = _resolved_url(source_url)
        if final and final != src.url:
            src.url = final
            src.save(update_fields=["url"])
            changed["source"] = True

    obj.intel_source_hash = new_hash
    obj.intel_last_edited_at = timezone.now()
    obj.save()

    _log_update(obj, changed)
    return changed


def refresh_hardware_article(obj, force=False):
    changed = {"text": False, "image": False, "source": False}
    src = _primary_source(obj)
    source_url = src.url if src else ""

    source_text = fetch_source_text(source_url)
    new_hash = pipeline.source_hash(obj.title, source_text or obj.ai_draft_body, obj.category)
    if new_hash == obj.intel_source_hash and obj.intel_last_edited_at is not None and not force:
        return None

    rewrite = ai_rewrite(obj.title, source_text, obj.category)
    if rewrite:
        obj.ai_summary = rewrite["summary"]
        obj.ai_draft_body = rewrite["body"]
        changed["text"] = True

    changed["image"] = refresh_article_image(
        obj, obj.title, obj.ai_summary or obj.ai_draft_body, obj.category, force=force, save=False
    )

    if src and source_url:
        final = _resolved_url(source_url)
        if final and final != src.url:
            src.url = final
            src.save(update_fields=["url"])
            changed["source"] = True

    obj.intel_source_hash = new_hash
    obj.intel_last_edited_at = timezone.now()
    obj.save()

    _log_update(obj, changed)
    return changed


def refresh_blog_post(obj, force=False):
    """Blog is conservative: image + SEO always; body ONLY if auto_managed
    (hand-written posts keep their prose). No timeline model on blog, so the
    refresh is recorded via intel_last_edited_at only."""
    changed = {"text": False, "image": False, "seo": False}
    body_text = obj.excerpt or obj.content[:1600]
    category = obj.category.slug if obj.category_id else "General Tech"

    new_hash = pipeline.source_hash(obj.title, obj.content, category)
    if new_hash == obj.intel_source_hash and obj.intel_last_edited_at is not None and not force:
        return None

    if obj.auto_managed:
        rewrite = ai_rewrite(obj.title, obj.content[:1600], category)
        if rewrite:
            obj.excerpt = rewrite["summary"][:300]
            obj.content = rewrite["body"]
            obj.meta_description = rewrite["summary"][:160]
            changed["text"] = changed["seo"] = True
    else:
        # SEO-only: keep body, refresh the meta description from the excerpt.
        if obj.excerpt and obj.meta_description != obj.excerpt[:160]:
            obj.meta_description = obj.excerpt[:160]
            changed["seo"] = True

    changed["image"] = refresh_article_image(
        obj, obj.title, body_text, category, force=force, save=False
    )

    obj.intel_source_hash = new_hash
    obj.intel_last_edited_at = timezone.now()
    obj.save()
    return changed


def _resolved_url(url):
    try:
        r = requests.head(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        return r.url
    except requests.RequestException:
        return ""


def _log_update(obj, changed):
    """Write a 'What's New' timeline entry describing the refresh (news +
    hardware only  they share the ArticleUpdate shape)."""
    parts = []
    if changed.get("text"):
        parts.append("content updated from source")
    if changed.get("image"):
        parts.append("image refreshed")
    if changed.get("source"):
        parts.append("source link updated")
    if not parts:
        return
    obj.updates.create(
        kind="update",
        title="Article automatically refreshed",
        description="The intelligent editor refreshed this article: " + ", ".join(parts) + ".",
    )


# --------------------------------------------------------------- run entry point

_REFRESHERS = {
    "news": ("news.models", "NewsDraft", {"status": "published"}, refresh_news_article),
    "hardware": ("hardware.models", "HardwareArticle", {"status": "published"}, refresh_hardware_article),
    "blog": ("blog.models", "Post", {"is_published": True}, refresh_blog_post),
}


def run_auto_edit(kind, force=False, limit=None):
    """Process due published rows of one kind. Returns a summary string."""
    import importlib

    if kind not in _REFRESHERS:
        raise ValueError(f"unknown auto-edit kind: {kind}")
    module_path, model_name, published_filter, refresher = _REFRESHERS[kind]
    model = getattr(importlib.import_module(module_path), model_name)

    qs = _due_queryset(model, published_filter)
    if limit:
        qs = qs[:limit]

    edited = skipped = failed = 0
    for obj in list(qs):
        try:
            result = refresher(obj, force=force)
            if result is None:
                skipped += 1
            else:
                edited += 1
        except Exception as exc:  # noqa: BLE001  one bad article must not kill the run
            failed += 1
            print(f"[auto_edit:{kind}] failed for #{obj.pk}: {exc}")
    return f"[auto_edit:{kind}] edited={edited} skipped={skipped} failed={failed}"
