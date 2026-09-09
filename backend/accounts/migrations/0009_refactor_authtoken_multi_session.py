import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_register_weekly_digest_periodic_task"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # OneToOneField -> ForeignKey: same underlying column, just drops the
        # uniqueness constraint on user_id so a user can hold more than one
        # token (one per logged-in device). related_name changes singular ->
        # plural since it's no longer a 1:1 accessor.
        migrations.AlterField(
            model_name="authtoken",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="auth_tokens",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="authtoken",
            name="device_label",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="authtoken",
            name="ip_address",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="authtoken",
            name="last_seen_at",
            # Existing rows get "now" as a one-off backfill (equivalent to
            # the interactive makemigrations prompt's option 1)  there's no
            # real historical last-seen data to backfill from.
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]
