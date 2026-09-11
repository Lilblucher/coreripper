"""Add the claude_ai kill switch, seeded OFF.

Sonnet-5 (the paid Anthropic path) stays switched off until the Anthropic API
account is funded. Everything stays wired: flip the switch in the Engine Room's
Feature Switches tab and every Sonnet-5 surface goes live with no code change.

Deliberately additive-only: an existing row is left exactly as the operator set
it, so re-running this can never silently switch a live feature back off.
"""
from django.db import migrations

FLAG_KEY = "claude_ai"


def seed_claude_flag(apps, schema_editor):
    from core.middleware import FLAG_DEFS

    label, description = FLAG_DEFS[FLAG_KEY]
    FeatureFlag = apps.get_model("core", "FeatureFlag")
    FeatureFlag.objects.get_or_create(
        key=FLAG_KEY,
        defaults={"label": label, "description": description, "enabled": False},
    )


def drop_claude_flag(apps, schema_editor):
    FeatureFlag = apps.get_model("core", "FeatureFlag")
    FeatureFlag.objects.filter(key=FLAG_KEY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_categoryimage"),
    ]

    operations = [
        migrations.RunPython(seed_claude_flag, drop_claude_flag),
    ]
