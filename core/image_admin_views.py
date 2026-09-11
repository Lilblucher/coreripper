from django.http import JsonResponse
from django.views.decorators.http import require_GET

from accounts.decorators import staff_required

from .models import CategoryImage


@require_GET
@staff_required
def admin_category_images_view(request):
    """List the real, CC-licensed Wikimedia Commons pool for one (app,
    category) pair, so an admin moderation card can offer alternate photos
    instead of the deterministic hash-picked one from
    core.category_images.get_article_image. Read-only and staff_required
    (not superuser_required) since blog's staff-gated editor needs it too,
    same as news/hardware's superuser admin panel. An app/category with no
    pool (e.g. blog, which has no CategoryImage rows at all today) honestly
    returns an empty list rather than fabricating options."""
    app = (request.GET.get("app") or "").strip()
    category = (request.GET.get("category") or "").strip()
    if not app or not category:
        return JsonResponse({"error": "missing_params", "message": "app and category are required."}, status=400)
    pool = CategoryImage.objects.filter(app=app, category=category).values(
        "id", "image_url", "thumb_url", "credit_name", "credit_url", "license_name"
    )
    return JsonResponse({"images": list(pool)})
