from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from blog.models import Post

from .models import Tool


@require_GET
def public_stats_view(request):
    """Real, live counts for marketing/landing-page stats  no auth required,
    nothing here is sensitive. Never hand-wave a number here; if it can't be
    counted from the database, it doesn't belong in this response."""
    return JsonResponse(
        {
            "total_tools": Tool.objects.count(),
            "dev_tools": Tool.objects.filter(category="dev-tools").count(),
            "ai_tools": Tool.objects.filter(category="ai-tools").count(),
            "network_tools": Tool.objects.filter(category="network-tools").count(),
            "tool_categories": Tool.objects.values("category").distinct().count(),
            "total_users": User.objects.filter(profile__email_verified=True).count(),
            "total_posts": Post.objects.filter(is_published=True).count(),
        }
    )
