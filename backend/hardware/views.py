from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from core.intel import resolved_article_image

from .models import CATEGORY_CHOICES, HardwareArticle
from .seo import build_article_jsonld, build_breadcrumb_jsonld

CATEGORY_LABELS = dict(CATEGORY_CHOICES)


def _site_root(request):
    return request.build_absolute_uri("/").rstrip("/")


def _source_json(source):
    return {"url": source.url, "name": source.name, "is_primary": source.is_primary}


def _update_json(update):
    return {
        "kind": update.kind, "kind_display": update.get_kind_display(),
        "title": update.title, "description": update.description,
        "created_at": update.created_at.isoformat(),
    }


def _article_summary_json(article):
    return {
        "id": article.id,
        "title": article.title,
        "status": article.status,
        "category": article.category,
        "category_display": CATEGORY_LABELS.get(article.category, article.category),
        "ai_summary": article.ai_summary,
        "created_at": article.created_at.isoformat(),
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "reading_time_minutes": article.computed_reading_time,
        "is_human_reviewed": article.is_human_reviewed,
        "image": resolved_article_image(article, "hardware", article.category),
    }


def _article_detail_json(article, request):
    data = _article_summary_json(article)
    site_root = _site_root(request)
    data.update(
        {
            "ai_draft_body": article.ai_draft_body,
            "last_updated_at": article.last_updated_at.isoformat() if article.last_updated_at else None,
            "sources": [_source_json(s) for s in article.sources.all()],
            "updates": [_update_json(u) for u in article.updates.all()],
            "primary_subject": (
                {"type": type(article.primary_subject).__name__, "id": article.primary_subject.pk,
                 "name": str(article.primary_subject)}
                if article.primary_subject else None
            ),
            "seo_jsonld": {
                "article": build_article_jsonld(article, site_root),
                "breadcrumb": build_breadcrumb_jsonld(
                    article, CATEGORY_LABELS.get(article.category, article.category), site_root
                ),
            },
        }
    )
    return data


@require_GET
def hardware_articles_view(request):
    qs = (
        HardwareArticle.objects.filter(status="published")
        .prefetch_related("sources", "updates")
        .order_by("-published_at")
    )
    category = request.GET.get("category")
    if category and category != "all":
        qs = qs.filter(category=category)
    return JsonResponse({"items": [_article_summary_json(a) for a in qs]})


@require_GET
def hardware_article_detail_view(request, pk):
    article = get_object_or_404(
        HardwareArticle.objects.prefetch_related("sources", "updates"), pk=pk, status="published"
    )
    return JsonResponse(_article_detail_json(article, request))
