"""Celery tasks for scheduled monitor checks + alerting.

Status/change-detection logic is written against the REAL result shapes of
each tool (verified by reading network_tools/*.py directly), not the shapes
guessed in PHASE2_MONITORING_ALERTS.md  several of those guesses were wrong:
  - dns: `result` is a plain IP string, not a dict with a "records" key.
  - ping: no "reachable" boolean; success/failure is the outer "status".
  - ssl_expiration already computes a clean "cert_status"
    (expired/critical/warning/valid) + "days_remaining"  no need to
    reinvent that grading here.
  - "security_grade" doesn't exist as a tool in this codebase at all, so
    it's not handled below.
"""
from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from network_tools.views import run_tool_internal

from .models import AlertLog, Monitor


@shared_task
def dispatch_due_monitors():
    """Runs every 5 minutes (register via django-celery-beat). Fast query +
    fan-out only  the actual check happens in run_monitor_check.

    The spec's F()-based "elapsed >= interval" comparison doesn't work as a
    single ORM filter (F() can't be used inside timedelta()), so this uses
    the DB filter only to narrow to "possibly due" (never checked, or last
    checked at least the minimum interval  15 min  ago), then does the
    precise per-row "has its own interval actually elapsed" check in Python.
    """
    now = timezone.now()
    due = Monitor.objects.filter(is_active=True).filter(
        Q(last_checked_at__isnull=True) | Q(last_checked_at__lte=now - timedelta(minutes=15))
    )
    for monitor in due.iterator():
        if monitor.last_checked_at is None:
            run_monitor_check.delay(monitor.id)
            continue
        elapsed_minutes = (now - monitor.last_checked_at).total_seconds() / 60
        if elapsed_minutes >= monitor.check_interval_minutes:
            run_monitor_check.delay(monitor.id)


@shared_task(rate_limit='5/m')  # global concurrency cap  see PHASE2_MONITORING_ALERTS.md §2b
def run_monitor_check(monitor_id):
    try:
        monitor = Monitor.objects.get(id=monitor_id)
    except Monitor.DoesNotExist:
        return

    result = run_tool_internal(monitor.tool_key, monitor.target)
    new_status = evaluate_status(monitor.tool_key, result)
    changed = has_meaningful_change(monitor.last_result_json, result, monitor.tool_key)

    if changed and monitor.last_result_json is not None:
        summary = describe_change(monitor.tool_key, monitor.last_result_json, result)
        alert = AlertLog.objects.create(
            monitor=monitor,
            change_summary=summary,
            previous_status=monitor.status,
            new_status=new_status,
        )
        # A broker hiccup here must not stop the monitor's own status/result
        # from being saved below  the check itself already succeeded; only
        # alert *delivery* is at risk, and it stays queued in the AlertLog
        # row (sent_email/sent_whatsapp default False) for a retry path to
        # pick up later rather than silently losing the whole check.
        #
        # Two gates, both must pass: this specific monitor's own
        # alert_email/alert_whatsapp flag, AND the account-wide
        # NotificationPreference toggle (settings.html's Notifications tab)
        #  the global toggle is a real kill-switch, not cosmetic.
        prefs = getattr(monitor.user, "notification_prefs", None)
        try:
            if monitor.alert_email and (prefs is None or prefs.email_alerts):
                send_email_alert.delay(monitor.id, alert.id)
            if monitor.alert_whatsapp and (prefs is None or prefs.whatsapp_alerts):
                send_whatsapp_alert.delay(monitor.id, alert.id)
        except Exception:
            pass

    monitor.status = new_status
    monitor.last_result_json = result
    monitor.last_checked_at = timezone.now()
    monitor.save(update_fields=["status", "last_result_json", "last_checked_at", "updated_at"])


def evaluate_status(tool_key, response):
    """response is the full run_tool_internal() envelope: {status, result|message}."""
    if response.get("status") != "success":
        return "alert"  # the tool call itself failed  host down, DNS failure, handshake failed, etc.

    result = response.get("result")

    if tool_key == "ssl_expiration":
        # result is a dict here; cert_status is already computed by the tool.
        cert_status = (result or {}).get("cert_status")
        if cert_status in ("expired", "critical"):
            return "alert"
        if cert_status == "warning":
            return "warning"
        return "ok"

    if tool_key == "ssl_info":
        # Raw ssl.getpeercert() dict, no built-in grading  success/failure
        # of the handshake itself is the only reliable signal here.
        return "ok"

    if tool_key == "http_status":
        category = (result or {}).get("category")
        if category in ("client_error", "server_error"):
            return "alert"
        if category == "redirect":
            return "warning"
        return "ok"

    if tool_key == "ping":
        loss_pct = (result or {}).get("loss_pct", 0)
        if loss_pct >= 50:
            return "warning"
        return "ok"

    if tool_key == "dns":
        # result is a plain IP string on success  resolving at all is "ok"
        # for v1; the has_meaningful_change() below is what actually flags
        # a changed IP as worth alerting on.
        return "ok"

    return "alert" if response.get("error") else "ok"


def has_meaningful_change(old_response, new_response, tool_key):
    if old_response is None:
        return False  # first check ever  nothing to compare against

    old_ok = old_response.get("status") == "success"
    new_ok = new_response.get("status") == "success"
    if old_ok != new_ok:
        return True  # flipped between working and broken  always worth alerting

    if not new_ok:
        return False  # still broken the same way  don't re-alert every cycle

    old_result, new_result = old_response.get("result"), new_response.get("result")

    if tool_key == "dns":
        return old_result != new_result  # result is a plain IP string

    relevant_keys = {
        "ssl_expiration": ["cert_status", "days_remaining", "issuer"],
        "http_status": ["status_code", "category"],
        "ping": ["loss_pct"],
    }.get(tool_key)

    if relevant_keys is None:
        return old_result != new_result

    old_result, new_result = old_result or {}, new_result or {}
    return any(old_result.get(k) != new_result.get(k) for k in relevant_keys)


def describe_change(tool_key, old_response, new_response):
    """Plain-English summary for the alert email/WhatsApp message."""
    old_ok = old_response.get("status") == "success"
    new_ok = new_response.get("status") == "success"

    if old_ok and not new_ok:
        return f"{new_response.get('message') or 'The check started failing.'}"
    if not old_ok and new_ok:
        return "The check is passing again."

    new_result = new_response.get("result") or {}
    old_result = old_response.get("result") or {}

    if tool_key == "ssl_expiration":
        return (
            f"SSL certificate status changed to '{new_result.get('cert_status')}' "
            f"({new_result.get('days_remaining')} days remaining)."
        )
    if tool_key == "http_status":
        return f"HTTP status changed from {old_result.get('status_code')} to {new_result.get('status_code')}."
    if tool_key == "ping":
        return f"Packet loss changed to {new_result.get('loss_pct')}%."
    if tool_key == "dns":
        return f"DNS resolution changed from {old_result} to {new_result}."
    return "The monitored result changed."


# Monitor.status values are internal shorthand; these are what a customer reads.
_STATE_WORDS = {
    "ok": "Healthy",
    "warning": "Degraded",
    "alert": "Failing",
    "pending": "Not yet checked",
}


@shared_task
def send_email_alert(monitor_id, alert_id):
    from django.conf import settings
    from django.core.mail import send_mail

    try:
        monitor = Monitor.objects.get(id=monitor_id)
        alert = AlertLog.objects.get(id=alert_id)
    except (Monitor.DoesNotExist, AlertLog.DoesNotExist):
        return

    check = monitor.get_tool_key_display()
    state = _STATE_WORDS.get(alert.new_status, alert.new_status)
    # Recovery reads very differently from a new fault, and the subject line is
    # often all a user sees on a phone lock screen - lead with which one it is.
    recovered = alert.new_status == "ok"
    headline = "Resolved" if recovered else ("Warning" if alert.new_status == "warning" else "Alert")

    send_mail(
        subject=f"[{headline}] {monitor.target} - {check}",
        message=(
            f"{'Your monitor has returned to normal.' if recovered else 'A monitored check has changed state.'}\n\n"
            f"Target      {monitor.target}\n"
            f"Check       {check}\n"
            f"State       {_STATE_WORDS.get(alert.previous_status, alert.previous_status)} -> {state}\n"
            f"Detected    {alert.triggered_at.strftime('%d %b %Y at %H:%M %Z')}\n\n"
            f"What changed:\n{alert.change_summary}\n\n"
            + (
                "No action needed - this message is a confirmation that the earlier "
                "issue has cleared.\n\n"
                if recovered
                else "We'll email you again as soon as this clears.\n\n"
            )
            + "Full history and settings for this monitor:\nwww.coreripper.site\n\n"
            "You're receiving this because email alerts are switched on for this "
            "monitor. You can change that from the Monitoring panel on your account.\n\n"
            "CoreRipper Monitoring"
        ),
        from_email=settings.EMAIL_FROM_ALERTS,
        recipient_list=[monitor.user.email],
    )
    alert.sent_email = True
    alert.save(update_fields=["sent_email"])


@shared_task
def send_whatsapp_alert(monitor_id, alert_id):
    """Deliver an alert over WhatsApp via monitors/whatsapp.py (the Octavian bot).

    That bot is an external process under a live WhatsApp Web session, which this
    task can't control  so a failure is expected, not exceptional, and isn't
    retried indefinitely. What it must never do is fail *silently*: the outcome
    is always written back to the AlertLog (sent_whatsapp, or whatsapp_error with
    a user-facing reason) so the dashboard shows what really happened instead of
    implying the alert was delivered.
    """
    from . import whatsapp

    try:
        monitor = Monitor.objects.get(id=monitor_id)
        alert = AlertLog.objects.get(id=alert_id)
    except (Monitor.DoesNotExist, AlertLog.DoesNotExist):
        return

    if not monitor.whatsapp_number:
        alert.whatsapp_error = "No WhatsApp number on file for this monitor."
        alert.save(update_fields=["whatsapp_error"])
        return

    recovered = alert.new_status == "ok"
    sent, error = whatsapp.send_message(
        monitor.whatsapp_number,
        # Kept to a few lines on purpose - this lands in a chat thread, not an
        # inbox, so the email's full detail block would read as spam here.
        f"*CoreRipper {'Resolved' if recovered else 'Alert'}*\n"
        f"{monitor.target} - {monitor.get_tool_key_display()}\n"
        f"{_STATE_WORDS.get(alert.previous_status, alert.previous_status)} -> "
        f"{_STATE_WORDS.get(alert.new_status, alert.new_status)}\n\n"
        f"{alert.change_summary}",
    )
    alert.sent_whatsapp = sent
    alert.whatsapp_error = "" if sent else error
    alert.save(update_fields=["sent_whatsapp", "whatsapp_error"])
    # A real send attempt is fresher evidence than the cached probe.
    whatsapp.invalidate_status_cache()
