"""Premium monitor CRUD + alert history. Same conventions as dashboard/views.py:
plain Django JSON views (no DRF), csrf_exempt (bearer-token auth, not session
cookies), strictly scoped to request.user."""

import json
import re

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from accounts.entitlements import entitlement, requires_plan

from . import whatsapp
from .models import MONITORABLE_TOOL_KEYS, AlertLog, Monitor

# Abuse brake on the test-message endpoint: it sends a real WhatsApp message to
# a user-supplied number, so it's the one endpoint here that could be used to
# spam a third party. Same cache pattern as payments/views.py::_charge_rate_limited.
TEST_MESSAGE_LIMIT = 5
TEST_MESSAGE_WINDOW_SECONDS = 3600


def _normalize_whatsapp_number(raw):
    # Digits only (country code + number)  matches what the Octavian bot's
    # /send endpoint expects for building a WhatsApp chat id (it strips
    # non-digits defensively too, but storing it clean avoids double meaning
    # when displayed back in the dashboard).
    return re.sub(r"[^0-9]", "", raw or "")

# Per-plan active-monitor cap lives in accounts.entitlements (Standard 3 /
# Pro 10). Kept as a module constant for the legacy import in accounts.views,
# where it now means "the highest cap any plan can have".
MAX_MONITORS_PER_USER = 10
VALID_INTERVALS = {choice[0] for choice in Monitor.CHECK_INTERVAL_CHOICES}


def _parse_json_body(request):
    try:
        return json.loads(request.body or b"{}"), None
    except (ValueError, UnicodeDecodeError):
        return None, JsonResponse({"error": "invalid_json"}, status=400)


def _monitor_json(monitor):
    return {
        "id": monitor.id,
        "tool_key": monitor.tool_key,
        "target": monitor.target,
        "check_interval_minutes": monitor.check_interval_minutes,
        "status": monitor.status,
        "last_checked_at": monitor.last_checked_at.isoformat() if monitor.last_checked_at else None,
        "last_result": monitor.last_result_json,
        "alert_email": monitor.alert_email,
        "alert_whatsapp": monitor.alert_whatsapp,
        "whatsapp_number": monitor.whatsapp_number,
        "is_active": monitor.is_active,
        "created_at": monitor.created_at.isoformat(),
    }


def _alert_json(alert):
    return {
        "id": alert.id,
        "triggered_at": alert.triggered_at.isoformat(),
        "change_summary": alert.change_summary,
        "previous_status": alert.previous_status,
        "new_status": alert.new_status,
        "sent_email": alert.sent_email,
        "sent_whatsapp": alert.sent_whatsapp,
        "whatsapp_error": alert.whatsapp_error,
        # Derived from the row's own outcome, not the monitor's current
        # alert_whatsapp flag  toggling the channel off later must not rewrite
        # the history of an alert that really was sent (or really did fail).
        "whatsapp_attempted": bool(alert.sent_whatsapp or alert.whatsapp_error),
        "seen_by_user": alert.seen_by_user,
    }


@csrf_exempt
@requires_plan("standard")
@require_http_methods(["GET", "POST"])
def monitors_view(request):
    if request.method == "GET":
        monitors = Monitor.objects.filter(user=request.user)
        return JsonResponse({"monitors": [_monitor_json(m) for m in monitors]})

    body, error = _parse_json_body(request)
    if error:
        return error

    tool_key = (body.get("tool_key") or "").strip()
    target = (body.get("target") or "").strip()
    interval = body.get("check_interval_minutes", 60)

    if not tool_key or not target:
        return JsonResponse({"error": "missing_field", "message": "'tool_key' and 'target' are required."}, status=400)
    if tool_key not in MONITORABLE_TOOL_KEYS:
        return JsonResponse(
            {"error": "invalid_tool", "message": f"'{tool_key}' can't be monitored. Choose one of: {', '.join(sorted(MONITORABLE_TOOL_KEYS))}."},
            status=400,
        )
    if interval not in VALID_INTERVALS:
        return JsonResponse(
            {"error": "invalid_interval", "message": f"check_interval_minutes must be one of {sorted(VALID_INTERVALS)}."},
            status=400,
        )
    monitor_cap = entitlement(request.user, "monitors")
    if Monitor.objects.filter(user=request.user).count() >= monitor_cap:
        return JsonResponse(
            {
                "error": "monitor_limit_reached",
                "monitor_cap": monitor_cap,
                "upgrade_url": "/pricing.html",
                "message": f"Your plan includes {monitor_cap} monitors. Upgrade for more.",
            },
            status=400,
        )
    if Monitor.objects.filter(user=request.user, tool_key=tool_key, target=target).exists():
        return JsonResponse(
            {"error": "duplicate_monitor", "message": "You're already monitoring this tool/target combination."},
            status=409,
        )

    alert_whatsapp = bool(body.get("alert_whatsapp", False))
    whatsapp_number = _normalize_whatsapp_number(body.get("whatsapp_number"))
    if alert_whatsapp and not whatsapp_number:
        return JsonResponse(
            {"error": "missing_field", "message": "'whatsapp_number' is required when alert_whatsapp is enabled."},
            status=400,
        )

    monitor = Monitor.objects.create(
        user=request.user,
        tool_key=tool_key,
        target=target[:255],
        check_interval_minutes=interval,
        alert_email=bool(body.get("alert_email", True)),
        alert_whatsapp=alert_whatsapp,
        whatsapp_number=whatsapp_number[:20],
    )
    return JsonResponse(_monitor_json(monitor), status=201)


@csrf_exempt
@requires_plan("standard")
@require_http_methods(["PATCH", "DELETE"])
def monitor_detail_view(request, monitor_id):
    monitor = get_object_or_404(Monitor, id=monitor_id, user=request.user)

    if request.method == "DELETE":
        monitor.delete()
        return JsonResponse({"status": "deleted"})

    body, error = _parse_json_body(request)
    if error:
        return error

    fields = []
    if "check_interval_minutes" in body:
        interval = body["check_interval_minutes"]
        if interval not in VALID_INTERVALS:
            return JsonResponse(
                {"error": "invalid_interval", "message": f"check_interval_minutes must be one of {sorted(VALID_INTERVALS)}."},
                status=400,
            )
        monitor.check_interval_minutes = interval
        fields.append("check_interval_minutes")
    if "alert_email" in body:
        monitor.alert_email = bool(body["alert_email"])
        fields.append("alert_email")
    if "alert_whatsapp" in body:
        monitor.alert_whatsapp = bool(body["alert_whatsapp"])
        fields.append("alert_whatsapp")
    if "whatsapp_number" in body:
        monitor.whatsapp_number = _normalize_whatsapp_number(body["whatsapp_number"])[:20]
        fields.append("whatsapp_number")
    if "is_active" in body:
        monitor.is_active = bool(body["is_active"])
        fields.append("is_active")

    if fields:
        fields.append("updated_at")
        monitor.save(update_fields=fields)
    return JsonResponse(_monitor_json(monitor))


@requires_plan("standard")
@require_http_methods(["GET"])
def monitor_alerts_view(request, monitor_id):
    monitor = get_object_or_404(Monitor, id=monitor_id, user=request.user)
    alerts = monitor.alerts.all()
    return JsonResponse({"alerts": [_alert_json(a) for a in alerts]})


@requires_plan("standard")
@require_http_methods(["GET"])
def whatsapp_status_view(request):
    """Is WhatsApp delivery actually possible right now? Lets the add-monitor
    form say so instead of offering a checkbox that quietly delivers nothing.
    Cached ~60s in monitors/whatsapp.py, so polling this is cheap."""
    return JsonResponse(whatsapp.probe_status())


@csrf_exempt
@requires_plan("standard")
@require_http_methods(["POST"])
def whatsapp_test_view(request):
    """Send one real test message to the given number, synchronously, and report
    the true outcome. This is the only way a user can confirm the channel works
    before trusting it with an outage alert  a queued Celery task couldn't
    answer them inline."""
    body, error = _parse_json_body(request)
    if error:
        return error

    number = _normalize_whatsapp_number(body.get("whatsapp_number"))
    if not number:
        return JsonResponse(
            {"error": "missing_field", "message": "Enter a WhatsApp number first."}, status=400
        )

    rl_key = f"wamsgrl:{request.user.id}"
    count = cache.get(rl_key, 0)
    if count >= TEST_MESSAGE_LIMIT:
        return JsonResponse(
            {
                "error": "rate_limited",
                "message": f"You've sent {TEST_MESSAGE_LIMIT} test messages in the last hour. Try again later.",
            },
            status=429,
        )
    cache.set(rl_key, count + 1, TEST_MESSAGE_WINDOW_SECONDS)

    sent, reason = whatsapp.send_message(
        number,
        "CoreRipper test message  your WhatsApp alerts are working. "
        "You'll get a message like this when one of your monitors changes status.",
    )
    whatsapp.invalidate_status_cache()

    if sent:
        return JsonResponse({"status": "sent", "message": "Test message sent  check WhatsApp."})
    # 503: the channel is unavailable, which is a server-side condition, not a
    # bad request  the number may well be fine.
    return JsonResponse({"error": "not_sent", "message": reason}, status=503)


@csrf_exempt
@requires_plan("standard")
@require_http_methods(["POST"])
def mark_alerts_seen_view(request):
    AlertLog.objects.filter(monitor__user=request.user, seen_by_user=False).update(seen_by_user=True)
    return JsonResponse({"status": "ok"})
