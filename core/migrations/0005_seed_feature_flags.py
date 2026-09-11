from django.db import migrations


def seed_flags(apps, schema_editor):
    from core.middleware import FLAG_DEFAULTS, FLAG_DEFS

    FeatureFlag = apps.get_model("core", "FeatureFlag")
    for key, (label, description) in FLAG_DEFS.items():
        FeatureFlag.objects.get_or_create(
            key=key,
            defaults={
                "label": label,
                "description": description,
                # Off-by-default flags (claude_ai) must seed off on a fresh
                # database too, not only via the later backfill migration.
                "enabled": FLAG_DEFAULTS.get(key, True),
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_featureflag"),
    ]

    operations = [
        migrations.RunPython(seed_flags, noop),
    ]
