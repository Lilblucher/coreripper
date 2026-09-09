import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from accounts.decorators import superuser_required

from .models import ArticleUpdate, NewsDraft
from .views import _news_detail_json


@require_GET
@superuser_required
def admin_news_view(request):
    """List NewsDraft rows of every status for the Engine Room cockpit's News
    tab  mirrors blog/views.py::admin_posts_view. Unlike blog authoring this
    is superuser-only, not staff: news moderation was never part of the
    Newsroom's blog-only scope."""
    qs = NewsDraft.objects.all().prefetch_related("sources", "updates")
    status = request.GET.get("status")
    if status and status != "all":
        qs = qs.filter(status=status)
    return JsonResponse({"items": [_news_detail_json(i) for i in qs]})


@csrf_exempt
@superuser_required
@require_http_methods(["PATCH"])
def admin_news_detail_view(request, pk):
    """Approve or reject a single draft. Body: {"status": "published"|"rejected"|"pending"}.
    Routed through NewsDraft.publish()/.reject() (not a direct field set) so
    the published_at stamp + timeline entry happen exactly once, same as
    Django's built-in /admin/ action (news/admin.py)  one shared
    implementation for both admin surfaces."""
    item = get_object_or_404(NewsDraft, pk=pk)

    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    new_status = body.get("status")
    if new_status not in dict(NewsDraft.STATUS_CHOICES):
        return JsonResponse({"error": "invalid_status"}, status=400)

    if new_status == "published":
        item.publish()
    elif new_status == "rejected":
        item.reject()
    else:
        item.status = new_status
        item.save(update_fields=["status"])
    return JsonResponse(_news_detail_json(item))


@csrf_exempt
@superuser_required
@require_http_methods(["POST"])
def admin_news_add_update_view(request, pk):
    """Log a manual Knowledge Timeline / What's New entry against a
    published draft (a new CVE detail, an RFC status change, a vendor
    advisory, ...). There's no automated change-detection crawler yet  this
    is the honest interim path, and it's the same ArticleUpdate model a
    future automated job would write into, so nothing here needs to change
    when that's built."""
    item = get_object_or_404(NewsDraft, pk=pk)

    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    kind = body.get("kind", "update")
    if kind not in dict(ArticleUpdate.KIND_CHOICES):
        return JsonResponse({"error": "invalid_kind"}, status=400)
    title = (body.get("title") or "").strip()
    if not title:
        return JsonResponse({"error": "missing_title"}, status=400)

    item.updates.create(kind=kind, title=title, description=(body.get("description") or "").strip())
    return JsonResponse(_news_detail_json(item), status=201)


@csrf_exempt
@superuser_required
@require_http_methods(["PATCH"])
def admin_news_image_view(request, pk):
    """Manually override a draft's image  the admin panel's "Change picture"
    action, fed by a category-pool pick (core.image_admin_views) or a fresh
    upload (blog's existing upload endpoint, reused as-is since it's generic
    file storage, not blog-specific logic). Body shape matches
    IntelImageMixin.apply_image_result()'s expected keys (image_url required;
    thumb_url/credit_name/credit_url/license_name/source_name/provider
    optional). Writes into the same intel_image_* slot the AI image pipeline
    uses, so resolved_article_image() picks the manual choice up unchanged
    a later auto-editor pass may still replace it, by design (no lock)."""
    item = get_object_or_404(NewsDraft, pk=pk)

    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    image_url = (body.get("image_url") or "").strip()
    if not image_url:
        return JsonResponse({"error": "missing_image_url"}, status=400)

    item.apply_image_result(body)
    item.save()
    return JsonResponse(_news_detail_json(item))
