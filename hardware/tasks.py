"""Celery task for hardware/gaming content ingestion  the automated
pipeline required by the spec, built against the provider architecture in
hardware/providers/. Now scheduled via Celery Beat (migration 0002)  the
registry stopped being empty once 4 real RSS publications were wired in
(hardware/providers/sources.py: Tom's Hardware, TechPowerUp, GSMArena,
PC Gamer), same trigger news/monitors' own beat schedules waited for.

Unlike news.tasks.aggregate_news, this does not AI-draft a rewritten body 
the original spec for hardware ingestion doesn't ask for that, and provider
excerpts (manufacturer announcements, driver notes, ...) are exactly the
kind of source where verbatim/near-verbatim technical detail matters more
than paraphrasing. Everything lands as status="pending" regardless; nothing
is public until a human reviews and publishes it, same moderation gate as
every other content type in this project.
"""
from celery import shared_task

from .models import CATEGORY_CHOICES, HardwareArticle, HardwareArticleSource
from .providers.registry import get_registered_providers

_VALID_CATEGORIES = {key for key, _ in CATEGORY_CHOICES}


@shared_task
def aggregate_hardware_content():
    providers = get_registered_providers()
    if not providers:
        return "No providers registered  nothing to ingest."

    created = []
    for provider in providers:
        try:
            items = provider.fetch()
        except Exception as exc:  # noqa: BLE001  one dead provider must not break the others
            print(f"[aggregate_hardware_content] provider '{provider.name}' failed: {exc}")
            continue

        for item in items:
            url = item.get("url")
            category = item.get("category")
            if not url or category not in _VALID_CATEGORIES:
                continue
            if HardwareArticleSource.objects.filter(url=url).exists():
                continue

            article = HardwareArticle.objects.create(
                title=item["title"],
                category=category,
                ai_summary=item.get("excerpt", ""),
                ai_draft_body=item.get("excerpt", ""),
            )
            HardwareArticleSource.objects.create(
                article=article, url=url, name=item.get("source_name", provider.name), is_primary=True,
            )
            # Best-effort accurate image (a miss keeps the per-category fallback).
            try:
                from core.intel.generate import refresh_article_image

                refresh_article_image(article, item["title"], item.get("excerpt", ""), category)
            except Exception as exc:  # noqa: BLE001  never break ingestion
                print(f"[aggregate_hardware_content] image resolve failed for {url}: {exc}")
            created.append(article)

    if created:
        return f"Created {len(created)} pending hardware article(s) from {len(providers)} provider(s)."
    return f"Ran {len(providers)} provider(s), nothing new."


@shared_task
def auto_edit_hardware():
    """Intelligent auto-editor pass over due published hardware articles
    (registered by data migration). Same refresh flow as news."""
    from core.intel.auto_editor import run_auto_edit

    return run_auto_edit("hardware")


@shared_task
def sync_hardware_spec_type(type_key):
    """Runs one hardware.providers.manager.sync_type() pass for a single
    type_key ("cpu"/"gpu"/"laptop"/"mobile_soc"). Scheduled on four separate
    cadences by migration 0004 (see that migration's own docstring for why
    the cadences differ per type). Shares no state with
    aggregate_hardware_content above  that task ingests *articles*, this one
    syncs the structured spec catalog (CPU/GPU/Laptop/MobileSoC rows)."""
    from .providers.manager import sync_type

    return sync_type(type_key)
