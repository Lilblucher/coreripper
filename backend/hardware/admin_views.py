import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from accounts.decorators import superuser_required

from .models import HardwareArticle, HardwareArticleUpdate
from .views import _article_detail_json


@require_GET
@superuser_required
def admin_hardware_articles_view(request):
    """List HardwareArticle rows of every status  mirrors
    news/admin_views.py::admin_news_view exactly. No cockpit tab built for
    this yet (out of scope, no UI requested this phase); Django's built-in
    /admin/ is the moderation surface today, same starting point news had."""
    qs = HardwareArticle.objects.all().prefetch_related("sources", "updates")
    status = request.GET.get("status")
    if status and status != "all":
        qs = qs.filter(status=status)
    return JsonResponse({"items": [_article_detail_json(a, request) for a in qs]})


@csrf_exempt
@superuser_required
@require_http_methods(["PATCH"])
def admin_hardware_article_detail_view(request, pk):
    article = get_object_or_404(HardwareArticle, pk=pk)

    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    new_status = body.get("status")
    if new_status not in dict(HardwareArticle.STATUS_CHOICES):
        return JsonResponse({"error": "invalid_status"}, status=400)

    if new_status == "published":
        article.publish()
    elif new_status == "rejected":
        article.reject()
    else:
        article.status = new_status
        article.save(update_fields=["status"])
    return JsonResponse(_article_detail_json(article, request))


@csrf_exempt
@superuser_required
@require_http_methods(["POST"])
def admin_hardware_article_add_update_view(request, pk):
    article = get_object_or_404(HardwareArticle, pk=pk)

    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    kind = body.get("kind", "update")
    if kind not in dict(HardwareArticleUpdate.KIND_CHOICES):
        return JsonResponse({"error": "invalid_kind"}, status=400)
    title = (body.get("title") or "").strip()
    if not title:
        return JsonResponse({"error": "missing_title"}, status=400)

    article.updates.create(kind=kind, title=title, description=(body.get("description") or "").strip())
    return JsonResponse(_article_detail_json(article, request), status=201)


@csrf_exempt
@superuser_required
@require_http_methods(["PATCH"])
def admin_hardware_article_image_view(request, pk):
    """Manually override an article's image  mirrors
    news/admin_views.py::admin_news_image_view exactly, see its docstring."""
    article = get_object_or_404(HardwareArticle, pk=pk)

    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    image_url = (body.get("image_url") or "").strip()
    if not image_url:
        return JsonResponse({"error": "missing_image_url"}, status=400)

    article.apply_image_result(body)
    article.save()
    return JsonResponse(_article_detail_json(article, request))
