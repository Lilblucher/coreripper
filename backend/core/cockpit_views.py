"""Engine-room endpoints for the admin cockpit: feature switches, a live
activity feed, and systems status. All superuser-only  staff accounts only
get blog authoring (see accounts.decorators.superuser_required)."""
import json
import socket
import time
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from accounts.decorators import superuser_required
from accounts.models import Payment, SupportTicket

from .middleware import FLAG_CACHE_KEY, FLAG_DEFAULTS, FLAG_DEFS, PUBLIC_FLAGS
from .models import FeatureFlag

PROCESS_STARTED_AT = time.time()


def _flag_json(flag):
    return {
        "key": flag.key,
        "label": flag.label,
        "description": flag.description,
        "enabled": flag.enabled,
        "updated_at": flag.updated_at.isoformat(),
    }


def _ensure_flags():
    """Self-heal: create any flag rows missing from FLAG_DEFS (e.g. a new
    feature added after the seed migration ran). A recreated row takes its
    FLAG_DEFAULTS state, so claude_ai can't come back on by being deleted."""
    existing = set(FeatureFlag.objects.values_list("key", flat=True))
    for key, (label, description) in FLAG_DEFS.items():
        if key not in existing:
            FeatureFlag.objects.create(
                key=key,
                label=label,
                description=description,
                enabled=FLAG_DEFAULTS.get(key, True),
            )


@require_GET
def public_features_view(request):
    """Unauthenticated read of the PUBLIC_FLAGS subset, so a static page can
    render a switched-off feature as unavailable rather than offering a click
    that only 503s. Read-only, and never exposes the rest of the table."""
    _ensure_flags()
    states = dict(FeatureFlag.objects.filter(key__in=PUBLIC_FLAGS).values_list("key", "enabled"))
    return JsonResponse(
        {"features": {k: bool(states.get(k, FLAG_DEFAULTS.get(k, True))) for k in PUBLIC_FLAGS}}
    )


@require_GET
@superuser_required
def admin_features_view(request):
    _ensure_flags()
    return JsonResponse({"features": [_flag_json(f) for f in FeatureFlag.objects.all()]})


@csrf_exempt
@require_http_methods(["PATCH"])
@superuser_required
def admin_feature_toggle_view(request, key):
    try:
        flag = FeatureFlag.objects.get(key=key)
    except FeatureFlag.DoesNotExist:
        return JsonResponse({"error": "unknown_feature"}, status=404)

    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        return JsonResponse({"error": "invalid_enabled", "message": "'enabled' must be true or false."}, status=400)

    flag.enabled = enabled
    flag.save(update_fields=["enabled", "updated_at"])
    cache.delete(FLAG_CACHE_KEY)  # take effect immediately, not after cache TTL
    print(f"[cockpit] {request.user.email} switched {flag.key} {'ON' if enabled else 'OFF'}")
    return JsonResponse({"feature": _flag_json(flag)})


@require_GET
@superuser_required
def admin_activity_view(request):
    """Flight recorder: the most recent events across every subsystem,
    merged and sorted. Only reports things this codebase actually tracks."""
    from blog.models import Post
    from monitors.models import AlertLog

    events = []

    for u in User.objects.order_by("-date_joined")[:15]:
        events.append({"ts": u.date_joined.isoformat(), "kind": "signup", "text": f"New account: {u.email}"})

    for p in Payment.objects.select_related("user").order_by("-created_at")[:15]:
        events.append({
            "ts": p.created_at.isoformat(), "kind": "payment",
            "text": f"Payment {p.status}: {p.amount} {p.currency}  {p.user.email}",
        })

    for a in AlertLog.objects.select_related("monitor__user").order_by("-triggered_at")[:15]:
        events.append({
            "ts": a.triggered_at.isoformat(), "kind": "alert",
            "text": f"Monitor {a.new_status.upper()}: {a.monitor.target} ({a.monitor.user.email})",
        })

    for t in SupportTicket.objects.order_by("-created_at")[:15]:
        events.append({
            "ts": t.created_at.isoformat(), "kind": "ticket",
            "text": f"Ticket {t.ticket_id} [{t.get_category_display()}]: {t.email}",
        })

    for post in Post.objects.filter(is_published=True).order_by("-published_at")[:10]:
        events.append({
            "ts": post.published_at.isoformat(), "kind": "blog",
            "text": f"Article published: {post.title}",
        })

    events.sort(key=lambda e: e["ts"], reverse=True)
    return JsonResponse({"events": events[:40]})


def _check_redis():
    url = urlparse(settings.CELERY_BROKER_URL)
    try:
        with socket.create_connection((url.hostname or "localhost", url.port or 6379), timeout=0.6):
            return True
    except OSError:
        return False


def _check_worker():
    try:
        from core_backend.celery import app as celery_app

        return bool(celery_app.control.ping(timeout=1.0))
    except Exception:
        return False


@require_GET
@superuser_required
def admin_systems_view(request):
    """Cockpit status lights. api/db are trivially up if this responds;
    redis is a socket check on the broker; worker is a real celery ping."""
    redis_ok = _check_redis()
    return JsonResponse({
        "systems": {
            "api": True,
            "database": True,
            "redis": redis_ok,
            "worker": _check_worker() if redis_ok else False,
            "email": bool(settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD),
            "google_auth": bool(getattr(settings, "GOOGLE_CLIENT_ID", "")),
        },
        "api_uptime_seconds": int(time.time() - PROCESS_STARTED_AT),
    })
