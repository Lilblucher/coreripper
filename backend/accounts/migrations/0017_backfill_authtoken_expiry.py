from django.conf import settings
from django.db import migrations
from django.utils import timezone


def backfill_expiry(apps, schema_editor):
    """Grandfather pre-expiry tokens: give every existing session a full
    refresh-lifetime window (60 days by default) instead of logging every
    device out at deploy time  but do make them expire eventually, since a
    null expiry means "immortal" and no live row should keep that."""
    AuthToken = apps.get_model("accounts", "AuthToken")
    deadline = timezone.now() + timezone.timedelta(days=settings.REFRESH_TOKEN_LIFETIME_DAYS)
    AuthToken.objects.filter(expires_at__isnull=True).update(expires_at=deadline)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0016_authtoken_expiry_refreshtoken"),
    ]

    operations = [
        migrations.RunPython(backfill_expiry, migrations.RunPython.noop),
    ]
