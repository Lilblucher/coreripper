from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from blog.models import Post as BlogPost
from core.intel import resolved_article_image
from core.models import Tool

from .embed_widgets import find_matching_tool_slug
from .models import NewsDraft
from .related_content import RELATED_BLOG_CATEGORY_SLUGS, RELATED_TOOL_SLUGS


def _news_summary_json(item):
    return {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "category": item.category,
        "category_display": item.get_category_display(),
        "source_name": item.source_name,
        "source_url": item.source_url,
        "trending_score": item.trending_score,
        "ai_summary": item.ai_summary,
        "created_at": item.created_at.isoformat(),
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "archived_at": item.archived_at.isoformat() if item.archived_at else None,
        "reading_time_minutes": item.computed_reading_time,
        "is_human_reviewed": item.is_human_reviewed,
        "image": resolved_article_image(item, "news", item.category),
    }


def _source_json(source):
    return {"url": source.url, "name": source.name, "is_primary": source.is_primary}


def _update_json(update):
    return {
        "kind": update.kind,
        "kind_display": update.get_kind_display(),
        "title": update.title,
        "description": update.description,
        "created_at": update.created_at.isoformat(),
    }


def _news_detail_json(item):
    data = _news_summary_json(item)
    updates = list(item.updates.all())
    data.update(
        {
            "ai_draft_body": item.ai_draft_body,
            "last_updated_at": item.last_updated_at.isoformat() if item.last_updated_at else None,
            "sources": [_source_json(s) for s in item.sources.all()],
            "updates": [_update_json(u) for u in updates],
        }
    )
    return data


@require_GET
def news_feed_view(request):
    """Public list of approved news items only  pending/rejected drafts are
    never exposed here, that's the whole point of the moderation queue."""
    qs = NewsDraft.objects.filter(status="published").order_by("-published_at")

    category = request.GET.get("category")
    if category and category != "all":
        qs = qs.filter(category=category)

    if request.GET.get("ordering") == "recently_updated":
        qs = qs.prefetch_related("updates")
    items = list(qs)
    # "recently_updated" backs the article sidebar's Recently Updated widget.
    # last_updated_at is a Python property (latest ArticleUpdate, falling
    # back to published_at), not a DB column, so this sorts in Python rather
    # than in the query  fine at this feed's current size (tens of rows,
    # not paginated), revisit with a DB-level annotation if that changes.
    if request.GET.get("ordering") == "recently_updated":
        items.sort(key=lambda i: i.last_updated_at or i.created_at, reverse=True)
    # else: newest-approved-first (-published_at) from the queryset above already applies.

    return JsonResponse({"items": [_news_summary_json(i) for i in items]})


@require_GET
def news_detail_view(request, pk):
    # Archived articles keep serving here (SEO: the URL must never 404 once
    # indexed)  only the feed/related-articles queries below drop them.
    item = get_object_or_404(
        NewsDraft.objects.prefetch_related("sources", "updates"),
        pk=pk, status__in=["published", "archived"],
    )
    return JsonResponse(_news_detail_json(item))


@require_GET
def news_archive_view(request):
    """Public list of archived articles (news.tasks.news_weekly_wrapup moves
    week-old published articles here rather than deleting them). Kept as its
    own page/link from news.html so archived articles stay internally linked
    and crawlable, not just reachable by a URL nothing points to."""
    qs = NewsDraft.objects.filter(status="archived")

    category = request.GET.get("category")
    if category and category != "all":
        qs = qs.filter(category=category)

    items = list(qs.order_by("-archived_at"))
    return JsonResponse({"items": [_news_summary_json(i) for i in items]})


def _tool_json(tool):
    return {"name": tool.name, "path": f"../{tool.path}", "category": tool.category}


def _related_article_json(item):
    return {
        "id": item.id, "title": item.title, "category": item.category,
        "category_display": item.get_category_display(), "ai_summary": item.ai_summary,
        "published_at": item.published_at.isoformat() if item.published_at else None,
    }


def _learn_more_json(post):
    return {"title": post.title, "excerpt": post.excerpt, "path": f"../blog/post.html?slug={post.slug}"}


@require_GET
def news_related_view(request, pk):
    """Backs the article page's Related Tools / Learn More / Related
    Articles sections and the sticky sidebar's Related Tools widget  one
    endpoint, since all three read the same curated mapping
    (news/related_content.py) keyed off this article's category. Every list
    can come back empty (no fake filler)  the frontend hides a section
    entirely rather than showing a placeholder when there's nothing real to
    recommend."""
    item = get_object_or_404(NewsDraft, pk=pk, status="published")

    tool_slugs = RELATED_TOOL_SLUGS.get(item.category, [])
    tools_by_slug = {
        t.slug: t for t in Tool.objects.filter(slug__in=tool_slugs, status="operational")
    }
    related_tools = [_tool_json(tools_by_slug[s]) for s in tool_slugs if s in tools_by_slug][:4]

    related_articles = list(
        NewsDraft.objects.filter(status="published", category=item.category)
        .exclude(pk=item.pk)
        .order_by("-published_at")[:4]
    )

    blog_category_slug = RELATED_BLOG_CATEGORY_SLUGS.get(item.category)
    learn_more = []
    if blog_category_slug:
        learn_more = list(
            BlogPost.objects.filter(is_published=True, category__slug=blog_category_slug).order_by(
                "-published_at"
            )[:3]
        )

    # "Try It Yourself" embedded widget  a real keyword match against this
    # article's own title/summary/body, not a category default. Most
    # articles legitimately get none (see news/embed_widgets.py's docstring).
    embedded_widget = None
    widget_slug = find_matching_tool_slug(f"{item.title} {item.ai_summary} {item.ai_draft_body}")
    if widget_slug:
        tool = Tool.objects.filter(slug=widget_slug, status="operational").first()
        if tool:
            embedded_widget = _tool_json(tool)

    return JsonResponse(
        {
            "related_tools": related_tools,
            "related_articles": [_related_article_json(a) for a in related_articles],
            "learn_more": [_learn_more_json(p) for p in learn_more],
            "embedded_widget": embedded_widget,
        }
    )
