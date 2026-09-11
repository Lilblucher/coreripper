"""Seed the five Claude-credit packs the pricing page has advertised since
Phase 2 (Starter 250/$0.99 … Ultimate 10000/$18.99). Unlike the PlanPrice seed
these start ACTIVE: the prices were already decided and shown publicly, and the
credit meter's zero-balance CTA quotes "Get 250 for $0.99" verbatim  the
purchasable list must match what the site promises. Idempotent: only seeds
into an empty table.
"""
from django.db import migrations

PACKS = [
    ("Starter", 250, "0.99"),
    ("Basic", 600, "1.99"),
    ("Standard", 1500, "3.99"),
    ("Pro", 4000, "8.99"),
    ("Ultimate", 10000, "18.99"),
]


def seed_packs(apps, schema_editor):
    CreditPackPrice = apps.get_model("payments", "CreditPackPrice")
    if CreditPackPrice.objects.exists():
        return
    for order, (label, credits, usd) in enumerate(PACKS):
        CreditPackPrice.objects.create(
            label=label,
            credits=credits,
            display_amount_usd=usd,
            is_active=True,
            sort_order=order,
        )


def unseed_packs(apps, schema_editor):
    CreditPackPrice = apps.get_model("payments", "CreditPackPrice")
    CreditPackPrice.objects.filter(label__in=[p[0] for p in PACKS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0005_creditpackprice"),
    ]

    operations = [
        migrations.RunPython(seed_packs, unseed_packs),
    ]
