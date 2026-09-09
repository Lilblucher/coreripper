from django.conf import settings
from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    """Create a wallet for every existing user, and grant the tier's monthly
    credit allowance to already-active paid subscribers (writing a real
    monthly_refresh ledger row and stamping last_refresh_at) so paying customers
    don't start Phase 1 at zero. Trialing/expired users get an empty wallet 
    trials carry no Claude credits by design."""
    User = apps.get_model(settings.AUTH_USER_MODEL.split(".", 1)[0], settings.AUTH_USER_MODEL.split(".", 1)[1])
    CreditWallet = apps.get_model("credits", "CreditWallet")
    CreditLedger = apps.get_model("credits", "CreditLedger")
    Subscription = apps.get_model("accounts", "Subscription")
    tier_credits = settings.TIER_MONTHLY_CREDITS
    now = timezone.now()

    for user in User.objects.all().iterator():
        wallet, _ = CreditWallet.objects.get_or_create(user=user)

    for sub in Subscription.objects.select_related("user").filter(status="active").iterator():
        grant = tier_credits.get(sub.plan, 0)
        if grant <= 0:
            continue
        wallet, _ = CreditWallet.objects.get_or_create(user=sub.user)
        if wallet.subscription_balance > 0:
            continue  # already granted (idempotent re-run)
        wallet.subscription_balance = grant
        wallet.last_refresh_at = now
        wallet.save(update_fields=["subscription_balance", "last_refresh_at", "updated_at"])
        CreditLedger.objects.create(
            user=sub.user,
            delta=grant,
            bucket="subscription",
            reason="monthly_refresh",
            operation="",
            tokens=0,
            balance_after=grant,
        )


def backwards(apps, schema_editor):
    # Wallets/ledger are dropped when the credits tables are, so nothing to undo.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("credits", "0001_initial"),
        ("accounts", "0013_map_active_to_status"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
