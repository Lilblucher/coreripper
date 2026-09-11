"""Celery task for the news aggregator  replaces the spec's cron-triggered
management command with a django_celery_beat schedule (see migration
0002_register_periodic_task), matching how monitors/dispatch_due_monitors and
accounts/send_weekly_digests are already scheduled in this project. No
separate cron/systemd timer needed.
"""
from celery import shared_task
from django.conf import settings
from time import sleep
from .models import NewsDraft
from .services import (
    fetch_trending_items,
    generate_ai_draft,
    generate_wrapup_summary,
    send_digest_email,
    send_wrapup_email,
)


@shared_task
def aggregate_news():
    """Runs 2x/day (registered via data migration). Fetch → dedup → score
    gate → AI draft → save as pending → digest email. A single item's AI
    call failing must not lose the rest of the run."""
    items = fetch_trending_items()
    new_drafts = []

    for item in items:
        if len(new_drafts) >= settings.NEWS_FEED_MAX_DRAFTS_PER_RUN:
            break
        if NewsDraft.objects.filter(source_url=item["url"]).exists():
            continue
        if not item["is_security_advisory"] and (
            item["score"] is None or item["score"] < settings.NEWS_FEED_TRENDING_THRESHOLD
        ):
            continue

        try:
            draft_content = generate_ai_draft(item)
        except Exception as exc:  # noqa: BLE001  one bad draft must not kill the run
            print(f"[aggregate_news] AI draft failed for {item['url']}: {exc}")
            continue

        obj = NewsDraft.objects.create(
            title=item["title"],
            source_url=item["url"],
            source_name=item["source_name"],
            category=item["category"],
            trending_score=item["score"] or 0,
            ai_summary=draft_content["summary"],
            ai_draft_body=draft_content["body"],
        )
        # Resolve an accurate, subject-specific image up front (best-effort
        # a miss just leaves the per-category fallback in place). Never let it
        # break the run.
        try:
            from core.intel.generate import refresh_article_image

            refresh_article_image(
                obj, item["title"], draft_content["summary"], item["category"]
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[aggregate_news] image resolve failed for {item['url']}: {exc}")

        new_drafts.append(obj)
        sleep(5)  # rate limit: pause between LLM calls to avoid 429s

    if new_drafts:
        try:
            send_digest_email(new_drafts)
        except Exception as exc:  # noqa: BLE001  drafts are already saved; email is best-effort
            print(f"[aggregate_news] digest email failed: {exc}")
        return f"Created {len(new_drafts)} draft(s), digest sent."
    return "No new drafts this run."


@shared_task
def auto_edit_news():
    """Intelligent auto-editor pass over due published news articles
    (registered by data migration). Refreshes text/image/SEO/sources and logs
    a timeline entry; unchanged sources are cheap no-ops."""
    from core.intel.auto_editor import run_auto_edit

    return run_auto_edit("news")


@shared_task
def news_weekly_wrapup():
    """Runs weekly (registered via data migration), one day before
    blog.tasks.auto_edit_blog and staggered ahead of
    hardware.tasks.auto_edit_hardware's monthly run  see the three beat
    migrations for the exact schedule. Every published news article lives on
    the main feed for exactly one wrap-up cycle: this summarizes the whole
    live published feed into one digest email for
    accounts.NotificationPreference.product_updates subscribers, then
    archives those articles (news.models.NewsDraft.archive())  never
    deletes them. Deleting indexed article URLs would tank their SEO value
    (dead links, lost backlink equity); archiving drops them off the main
    feed/related-articles surfaces while their own detail page keeps serving
    at the same URL, and news_archive_view/news.html's archive link keep them
    internally linked and crawlable. A failure summarizing or emailing one
    subscriber must not stop the archive pass."""
    from accounts.models import NotificationPreference
    from django.contrib.auth.models import User

    articles = list(NewsDraft.objects.filter(status="published").order_by("-published_at"))
    if not articles:
        return "No published articles  nothing to wrap up."

    try:
        summary = generate_wrapup_summary(articles)
    except Exception as exc:  # noqa: BLE001  a failed AI summary must not block the archive pass
        print(f"[news_weekly_wrapup] AI summary failed: {exc}")
        summary = None

    user_ids = NotificationPreference.objects.filter(product_updates=True).values_list("user_id", flat=True)
    sent = 0
    for user in User.objects.filter(id__in=user_ids):
        try:
            send_wrapup_email(user, articles, summary)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[news_weekly_wrapup] email failed for {user.email}: {exc}")

    for article in articles:
        article.archive()
    return f"Wrapped up {len(articles)} article(s), emailed {sent} subscriber(s), archived the feed."
