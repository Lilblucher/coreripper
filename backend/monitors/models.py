"""Premium monitoring: scheduled re-checks of a tool/target, with email
(and eventually WhatsApp) alerts on meaningful change. See
PHASE2_MONITORING_ALERTS.md for the full spec this implements.

tool_key must match /api/toolbox/?tool=... (core.Tool.tool_key), reused as-is
 same convention as dashboard.SavedResult. Restricted to a known-monitorable
subset via MONITORABLE_TOOLS rather than a free CharField, specifically
because this project has a recurring bug source of frontend/spec tool_key
strings drifting from the backend's real registry (the original phase spec
itself used "ssl_checker"/"http_status_checker"/"dns_lookup"/"security_grade" 
none of which are real tool_key values; the real ones are below, and
"security_grade" isn't a tool that exists in this codebase at all).
"""

from django.conf import settings
from django.db import models

# tool_key -> human label, for tools that produce a status worth watching over
# time. Extend evaluate_status()/has_meaningful_change() in tasks.py together
# with this list when adding a new monitorable tool.
MONITORABLE_TOOLS = [
    ("ssl_info", "SSL Certificate Checker"),
    ("ssl_expiration", "SSL Expiration Checker"),
    ("ping", "Ping Tool"),
    ("http_status", "HTTP Status Checker"),
    ("dns", "DNS Lookup"),
]
MONITORABLE_TOOL_KEYS = {key for key, _ in MONITORABLE_TOOLS}


class Monitor(models.Model):
    CHECK_INTERVAL_CHOICES = [
        (15, "15 minutes"),
        (30, "30 minutes"),
        (60, "1 hour"),
        (360, "6 hours"),
        (1440, "24 hours"),
        (10080, "Weekly"),
    ]
    STATUS_CHOICES = [
        ("ok", "OK"),
        ("warning", "Warning"),
        ("alert", "Alert"),
        ("pending", "Pending first check"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="monitors")
    tool_key = models.CharField(max_length=64, choices=MONITORABLE_TOOLS)
    target = models.CharField(max_length=255)
    check_interval_minutes = models.IntegerField(choices=CHECK_INTERVAL_CHOICES, default=60)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_result_json = models.JSONField(null=True, blank=True)
    alert_email = models.BooleanField(default=True)
    # WhatsApp alerting delivers through the Octavian bot (monitors/whatsapp.py)
    # and IS exposed in the dashboard's add-monitor form. Because that bot is an
    # external process that can be down or unlinked, the honesty guarantee moved
    # from "don't offer the option" to "never claim a delivery that didn't
    # happen": the form gates on whatsapp.probe_status() and every failed send
    # records its reason in AlertLog.whatsapp_error.
    alert_whatsapp = models.BooleanField(default=False)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "tool_key", "target"], name="uniq_monitor_per_user_tool_target")
        ]

    def __str__(self):
        return f"{self.user} · {self.tool_key} · {self.target}"


class AlertLog(models.Model):
    monitor = models.ForeignKey(Monitor, on_delete=models.CASCADE, related_name="alerts")
    triggered_at = models.DateTimeField(auto_now_add=True)
    change_summary = models.TextField()
    previous_status = models.CharField(max_length=16)
    new_status = models.CharField(max_length=16)
    sent_email = models.BooleanField(default=False)
    sent_whatsapp = models.BooleanField(default=False)
    # Why a WhatsApp send didn't land, when alert_whatsapp was on and it failed.
    # Blank means either "not attempted" or "delivered"  sent_whatsapp is what
    # disambiguates. Rendered verbatim in the dashboard's alert history, so it
    # holds a user-facing sentence, not an exception repr.
    whatsapp_error = models.CharField(max_length=200, blank=True)
    seen_by_user = models.BooleanField(default=False)

    class Meta:
        ordering = ["-triggered_at"]
        indexes = [models.Index(fields=["monitor", "triggered_at"])]

    def __str__(self):
        return f"{self.monitor} · {self.triggered_at}"
