from django.db import migrations
from django.utils import timezone

from accounts.migration_helpers import classify_legacy_subscription as classify


def forwards(apps, schema_editor):
    Subscription = apps.get_model("accounts", "Subscription")
    Payment = apps.get_model("accounts", "Payment")
    Profile = apps.get_model("accounts", "Profile")
    now = timezone.now()

    for sub in Subscription.objects.all().iterator():
        paid = Payment.objects.filter(
            user_id=sub.user_id, status="paid", activated_at__isnull=False
        )
        has_paid = paid.exists()
        new_status, new_plan = classify(
            plan=sub.plan,
            active=sub.active,
            expires_at=sub.expires_at,
            has_paid_payment=has_paid,
            now=now,
        )
        sub.status = new_status
        sub.plan = new_plan
        sub.current_period_end = sub.expires_at
        if new_status == "active" and has_paid:
            latest = paid.order_by("-activated_at").first()
            sub.current_period_start = latest.activated_at
        elif new_status == "trialing":
            sub.current_period_start = sub.created_at
        sub.renewal_state = "not_due"
        sub.cancel_at_period_end = False
        sub.save(
            update_fields=[
                "status",
                "plan",
                "current_period_start",
                "current_period_end",
                "renewal_state",
                "cancel_at_period_end",
                "updated_at",
            ]
        )

    # Everyone who predates the email-verification requirement is grandfathered
    # in as already verified.
    Profile.objects.update(email_verified=True)


def backwards(apps, schema_editor):
    # Best-effort reverse: restore the boolean from status so 0014 can re-add it
    # cleanly if rolled back. (active still exists at this migration state.)
    Subscription = apps.get_model("accounts", "Subscription")
    for sub in Subscription.objects.all().iterator():
        sub.active = sub.status in ("active", "trialing") and sub.plan != "free"
        sub.plan = "premium" if sub.active else "free"
        sub.save(update_fields=["active", "plan", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_profile_cookie_consent_version_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
