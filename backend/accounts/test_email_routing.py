"""Every outgoing email leaves from the sender that owns it: security@ for
credentials, billing@ for money, alert@ for monitoring, support@ for tickets.
These are one-line `from_email=` arguments scattered across five apps, so a
copy-paste of a nearby send_mail() is exactly how one silently regresses to the
wrong address  which a user only notices as a receipt arriving from Security.

Same offline-SQLite runner as the rest of the suite:
    manage.py test accounts --settings=core_backend.test_settings
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase


class EmailRoutingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="route@example.com", email="route@example.com", password="pw12345678"
        )
        # The reset cooldown lives in the real (shared) Redis cache, not the
        # test DB, so it survives between runs and would 429 the second one.
        # Delete just this user's key rather than flushing the whole cache.
        cache.delete(f"password-reset-cooldown:{self.user.email}")
        mail.outbox = []

    def test_verification_from_security(self):
        from accounts.views import _send_verification_code
        _send_verification_code(self.user)
        self.assertEqual(mail.outbox[-1].from_email, settings.EMAIL_FROM_SECURITY)

    def test_password_reset_from_security(self):
        r = self.client.post(
            "/api/accounts/forgot-password/",
            data='{"email": "route@example.com"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(mail.outbox[-1].from_email, settings.EMAIL_FROM_SECURITY)

    def test_monitor_alert_from_alerts(self):
        from monitors.models import AlertLog, Monitor
        from monitors.tasks import send_email_alert
        m = Monitor.objects.create(user=self.user, tool_key="http_status", target="example.com")
        a = AlertLog.objects.create(monitor=m, change_summary="x", previous_status="up", new_status="down")
        send_email_alert(m.id, a.id)
        self.assertEqual(mail.outbox[-1].from_email, settings.EMAIL_FROM_ALERTS)

    def test_renewal_notice_from_billing(self):
        from datetime import timedelta
        from django.utils import timezone
        from credits.tasks import request_renewals
        sub = self.user.subscription
        sub.plan = "pro"
        sub.status = "active"
        sub.renewal_state = "not_due"
        sub.current_period_end = timezone.now() + timedelta(days=1)
        sub.save()
        request_renewals()
        self.assertEqual(mail.outbox[-1].from_email, settings.EMAIL_FROM_BILLING)

    def test_support_ticket_from_support(self):
        r = self.client.post(
            "/api/accounts/support/tickets/",
            data={
                "email": "route@example.com",
                "name": "Route",
                "category": "technical",
                "domain_or_ip": "example.com",
                "description": "test",
            },
        )
        self.assertEqual(r.status_code, 201, r.content)
        senders = {m.from_email for m in mail.outbox}
        self.assertEqual(senders, {settings.EMAIL_FROM_SUPPORT})
        self.assertIn(settings.SUPPORT_EMAIL, mail.outbox[0].to)
