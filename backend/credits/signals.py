from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CreditWallet


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_credit_wallet(sender, instance, created, **kwargs):
    """Every user gets a wallet at 0/0 so run_ai never has to null-check it 
    mirrors accounts.models.create_free_subscription. get_or_create keeps it
    idempotent for the data-migration backfill of pre-existing users."""
    if created:
        CreditWallet.objects.get_or_create(user=instance)
