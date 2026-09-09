import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from accounts.decorators import superuser_required

from .decorators import premium_required
from .models import Tool

CATEGORY_LABELS = {
    "dev-tools": "Developer",
    "ai-tools": "AI Productivity",
    "network-tools": "Network",
}


@require_GET
@premium_required
def runnable_tools_view(request):
    """Tools runnable from the dashboard via /api/toolbox/?tool=<tool_key>  the
    authoritative tool_key registry, so the dashboard never hardcodes a second
    copy of this list (see DASHBOARD_FRONTEND_INSTRUCTIONS.md §4)."""
    tools = Tool.objects.exclude(tool_key="").filter(status="operational")
    return JsonResponse({
        "tools": [
            {"tool_key": t.tool_key, "name": t.name, "category": CATEGORY_LABELS.get(t.category, t.category)}
            for t in tools
        ]
    })


def _tool_json(tool):
    return {
        "id": tool.id,
        "name": tool.name,
        "slug": tool.slug,
        "category": tool.category,
        "path": tool.path,
        "status": tool.status,
        "notes": tool.notes,
        "updated_at": tool.updated_at.isoformat(),
    }


@require_GET
@superuser_required
def admin_tools_view(request):
    tools = Tool.objects.all()
    return JsonResponse({"tools": [_tool_json(t) for t in tools]})


@csrf_exempt
@superuser_required
@require_http_methods(["PUT"])
def admin_tool_detail_view(request, tool_id):
    tool = get_object_or_404(Tool, id=tool_id)
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    status = body.get("status")
    if status not in dict(Tool.STATUS_CHOICES):
        return JsonResponse({"error": "invalid_status"}, status=400)

    tool.status = status
    tool.notes = body.get("notes", tool.notes)
    tool.save(update_fields=["status", "notes", "updated_at"])
    return JsonResponse(_tool_json(tool))
