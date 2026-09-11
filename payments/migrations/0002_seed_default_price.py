"""Seed one INACTIVE example price so the Engine Room's Pricing tab has a
concrete row to edit. Nothing is public or purchasable until the admin flips
is_active  the user hasn't decided on prices yet, and this project never
shows a price the admin didn't set.
"""
from django.db import migrations


def seed_default_price(apps, schema_editor):
    PlanPrice = apps.get_model("payments", "PlanPrice")
    if not PlanPrice.objects.exists():
        PlanPrice.objects.create(
            label="Premium Monthly",
            plan="premium",
            display_amount_usd="12.00",
            amount_zmw="330.00",
            period_days=30,
            is_active=False,
            sort_order=0,
        )


def unseed_default_price(apps, schema_editor):
    PlanPrice = apps.get_model("payments", "PlanPrice")
    PlanPrice.objects.filter(label="Premium Monthly", is_active=False).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_default_price, unseed_default_price),
    ]
