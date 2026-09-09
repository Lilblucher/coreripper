from django.db import migrations


def paid_to_premium(apps, schema_editor):
    """Legacy data fix: early Subscription rows were written with plan='paid'
    before the model's PLAN_CHOICES settled on 'free'/'premium'. is_premium
    checks plan == 'premium' exactly, so any row still saying 'paid' silently
    reads as non-premium. See ACCESS_MATRIX_IMPLEMENTATION.md §1."""
    Subscription = apps.get_model("accounts", "Subscription")
    Subscription.objects.filter(plan="paid").update(plan="premium")


def premium_to_paid(apps, schema_editor):
    # Not a meaningful reverse (we can't distinguish originally-'paid' rows
    # from rows that became 'premium' through normal use since forward-running
    # this migration)  no-op reverse is safer than mislabeling rows.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_passwordresettoken_attempts_and_more"),
    ]

    operations = [
        migrations.RunPython(paid_to_premium, premium_to_paid),
    ]
