import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from accounts.decorators import staff_required

from .models import Category, Post


def _parse_json_body(request):
    try:
        return json.loads(request.body or b"{}"), None
    except (ValueError, UnicodeDecodeError):
        return None, JsonResponse({"error": "invalid_json"}, status=400)


def _category_json(category):
    return {
        "name": category.name,
        "slug": category.slug,
        "description": category.description,
    }


def _post_summary_json(post):
    return {
        "id": post.id,
        "title": post.title,
        "slug": post.slug,
        "excerpt": post.excerpt,
        "cover_image_url": post.cover_image_url,
        "category": _category_json(post.category),
        "author_name": post.author_name,
        "author_initials": post.author_initials,
        "reading_time_minutes": post.computed_reading_time,
        "is_published": post.is_published,
        "published_at": post.published_at.isoformat() if post.published_at else None,
    }


def _post_detail_json(post):
    data = _post_summary_json(post)
    data.update(
        {
            "content": post.content,
            "meta_description": post.meta_description,
            "updated_at": post.updated_at.isoformat(),
        }
    )
    return data


# ---------------------------------------------------------------- public API


@require_GET
def categories_view(request):
    return JsonResponse({"categories": [_category_json(c) for c in Category.objects.all()]})


@require_GET
def posts_view(request):
    qs = Post.objects.filter(is_published=True).select_related("category")

    category = request.GET.get("category")
    if category and category != "all":
        qs = qs.filter(category__slug=category)

    search = (request.GET.get("search") or "").strip()
    if search:
        from django.db.models import Q

        qs = qs.filter(Q(title__icontains=search) | Q(excerpt__icontains=search))

    return JsonResponse({"posts": [_post_summary_json(p) for p in qs]})


@require_GET
def post_detail_view(request, slug):
    post = get_object_or_404(Post, slug=slug, is_published=True)
    return JsonResponse(_post_detail_json(post))


# ----------------------------------------------------------------- admin API


# Keep in sync with the frontend file-picker accept list in admin.html.
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


@csrf_exempt
@staff_required
@require_http_methods(["POST"])
def admin_upload_image_view(request):
    """Multipart image upload for article bodies and covers, picked straight
    from the author's device  no server filesystem access required on their
    end. Saves to core_backend.urls.BLOG_IMAGES_DIR, a directory OUTSIDE the
    git repo on purpose: VS Code Live Server (serving the frontend at dev
    time) watches the whole repo by default, and a write inside it mid-edit
    used to trigger a live-reload that wiped the open editor. Served back at
    the matching /blog-images/<file> route in core_backend/urls.py."""
    import os
    import secrets

    from django.utils import timezone as tz
    from django.utils.text import slugify as dj_slugify

    from core_backend.urls import BLOG_IMAGES_DIR

    upload = request.FILES.get("image")
    if upload is None:
        return JsonResponse({"error": "missing_image", "message": "Attach the file under the 'image' field."}, status=400)
    if upload.size > MAX_IMAGE_BYTES:
        return JsonResponse({"error": "too_large", "message": "Images must be 5MB or smaller."}, status=400)

    root, ext = os.path.splitext(upload.name)
    ext = ext.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return JsonResponse(
            {"error": "bad_type", "message": f"Allowed image types: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}"},
            status=400,
        )

    subdir = tz.now().strftime("%Y/%m")
    dest_dir = BLOG_IMAGES_DIR / subdir
    os.makedirs(dest_dir, exist_ok=True)
    filename = f"{dj_slugify(root)[:60] or 'image'}-{secrets.token_hex(4)}{ext}"
    dest = dest_dir / filename
    with open(dest, "wb") as f:
        for chunk in upload.chunks():
            f.write(chunk)

    url = request.build_absolute_uri(f"/media/blog-images/{subdir}/{filename}")
    return JsonResponse({"url": url, "name": upload.name}, status=201)


@csrf_exempt
@staff_required
@require_http_methods(["GET", "POST"])
def admin_posts_view(request):
    if request.method == "GET":
        qs = Post.objects.all().select_related("category")
        return JsonResponse({"posts": [_post_detail_json(p) for p in qs]})

    body, error = _parse_json_body(request)
    if error:
        return error
    return _create_or_update_post(body)


@csrf_exempt
@staff_required
@require_http_methods(["GET", "PUT", "DELETE"])
def admin_post_detail_view(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    if request.method == "GET":
        return JsonResponse(_post_detail_json(post))

    if request.method == "DELETE":
        post.delete()
        return JsonResponse({"deleted": True})

    body, error = _parse_json_body(request)
    if error:
        return error
    return _create_or_update_post(body, post=post)


def _create_or_update_post(body, post=None):
    title = (body.get("title") or "").strip()
    category_slug = body.get("category")
    excerpt = (body.get("excerpt") or "").strip()
    content = body.get("content") or ""

    if not title or not category_slug or not excerpt or not content:
        return JsonResponse(
            {"error": "missing_field", "message": "title, category, excerpt, and content are required."},
            status=400,
        )

    try:
        category = Category.objects.get(slug=category_slug)
    except Category.DoesNotExist:
        return JsonResponse({"error": "invalid_category"}, status=400)

    is_new = post is None
    if post is None:
        post = Post()

    post.title = title
    post.category = category
    post.excerpt = excerpt
    post.content = content
    post.cover_image_url = (body.get("cover_image_url") or "").strip()
    post.meta_description = (body.get("meta_description") or excerpt)[:160]
    post.author_name = body.get("author_name") or post.author_name or "CoreRipper Team"
    post.author_initials = body.get("author_initials") or post.author_initials or "CL"
    post.reading_time_minutes = int(body.get("reading_time_minutes") or 0)

    custom_slug = (body.get("slug") or "").strip()
    if custom_slug:
        post.slug = custom_slug
    elif not post.slug:
        post.slug = slugify(title)

    was_published = post.is_published
    post.is_published = bool(body.get("is_published"))
    if not was_published and post.is_published:
        post.published_at = None  # let save() stamp "now" the first time it's published

    post.save()
    return JsonResponse(_post_detail_json(post), status=201 if is_new else 200)


@require_GET
@staff_required
def admin_categories_view(request):
    return JsonResponse({"categories": [_category_json(c) for c in Category.objects.all()]})
