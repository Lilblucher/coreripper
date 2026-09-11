"""Daily subscription-lifecycle beat tasks. All idempotent (safe to re-run any
number of times per day) and registered via a data migration
(credits/0003_register_periodic_tasks), the same pattern as every other
scheduled task in this project. Times are UTC; ordering matters (02:00 → 02:40).

Each task wraps per-subscription work so one bad row never aborts the run, and
returns a short summary string like the existing tasks.
"""
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from accounts.models import Subscription

PAID_TIERS = ("lite", "standard", "pro")


def _wallet(user):
    from .models import CreditWallet

    wallet, _ = CreditWallet.objects.get_or_create(user=user)
    return wallet


@shared_task
def expire_trials():
    """Trialing subscriptions whose period ended → expired/free (no grace for
    trials). Zero any stray subscription credits."""
    now = timezone.now()
    count = 0
    qs = Subscription.objects.filter(status="trialing", current_period_end__lt=now)
    for sub in qs.select_related("user").iterator():
        with transaction.atomic():
            sub.status = "expired"
            sub.plan = "free"
            sub.renewal_state = "not_due"
            sub.save(update_fields=["status", "plan", "renewal_state", "updated_at"])
            _wallet(sub.user).reset_subscription(0)
        count += 1
    return f"expired {count} trials"


@shared_task
def request_renewals():
    """Active paid subs due in <= RENEWAL_NOTICE_DAYS → awaiting_payment + one
    nudge email. Idempotent via the renewal_state filter (one transition, one
    email); settle_payment resets it back to not_due, closing the loop."""
    now = timezone.now()
    cutoff = now + timedelta(days=settings.RENEWAL_NOTICE_DAYS)
    count = 0
    qs = Subscription.objects.filter(
        status="active",
        plan__in=PAID_TIERS,
        renewal_state="not_due",
        cancel_at_period_end=False,
        current_period_end__lte=cutoff,
    )
    for sub in qs.select_related("user").iterator():
        sub.renewal_state = "awaiting_payment"
        sub.save(update_fields=["renewal_state", "updated_at"])
        try:
            end = sub.current_period_end.strftime("%d %b %Y") if sub.current_period_end else "soon"
            send_mail(
                subject=f"Your CoreRipper {sub.plan.title()} plan renews on {end}",
                message=(
                    f"Hello{' ' + sub.user.first_name if sub.user.first_name else ''},\n\n"
                    f"This is a reminder that your {sub.plan.title()} plan is due for "
                    f"renewal on {end}.\n\n"
                    "CoreRipper doesn't charge cards automatically, so nothing will be "
                    "taken without you approving it. To keep your premium tools and your "
                    "monthly credit allowance running without a gap, renew from your "
                    "Billing page:\n\n"
                    "  www.coreripper.site\n\n"
                    "If you'd rather not continue, you don't need to do anything. Your "
                    "account will move to the Free plan when the period ends, and any "
                    "credits you bought separately stay in your wallet until they "
                    "expire.\n\n"
                    "CoreRipper Billing"
                ),
                from_email=settings.EMAIL_FROM_BILLING,
                recipient_list=[sub.user.email],
                fail_silently=False,
            )
        except Exception as exc:  # a failed nudge must not un-transition the row
            print(f"[request_renewals] email failed for {sub.user.email}: {exc}")
        count += 1
    return f"requested renewal for {count} subs"


@shared_task
def refresh_subscription_credits():
    """Monthly credit grant *within* a long paid period. Settlement already
    refreshes on payment, so this only covers subscribers whose period is longer
    than a month: active paid, within period, last refreshed null or > 30 days
    ago → reset to the tier grant. Idempotent via last_refresh_at."""
    now = timezone.now()
    threshold = now - timedelta(days=30)
    count = 0
    qs = Subscription.objects.filter(
        status="active", plan__in=PAID_TIERS, current_period_end__gte=now
    )
    for sub in qs.select_related("user").iterator():
        wallet = _wallet(sub.user)
        if wallet.last_refresh_at is not None and wallet.last_refresh_at > threshold:
            continue
        wallet.reset_subscription(settings.TIER_MONTHLY_CREDITS.get(sub.plan, 0))
        count += 1
    return f"refreshed {count} wallets"


@shared_task
def expire_unrenewed():
    """Active subs past their period end: cancel_at_period_end → cancelled/free
    now; else within RENEWAL_GRACE_DAYS → grace (features keep working, is_premium
    stays True because status is still 'active'); else → expired/free. Pack credits
    always survive plan changes (they expire only on their own 12-month clock)."""
    now = timezone.now()
    grace_cutoff = now - timedelta(days=settings.RENEWAL_GRACE_DAYS)
    cancelled = graced = expired = 0
    qs = Subscription.objects.filter(status="active", current_period_end__lt=now)
    for sub in qs.select_related("user").iterator():
        if sub.cancel_at_period_end:
            with transaction.atomic():
                sub.status = "cancelled"
                sub.plan = "free"
                sub.renewal_state = "not_due"
                sub.save(update_fields=["status", "plan", "renewal_state", "updated_at"])
                _wallet(sub.user).reset_subscription(0)
            cancelled += 1
        elif sub.current_period_end >= grace_cutoff:
            if sub.renewal_state != "grace":
                sub.renewal_state = "grace"
                sub.save(update_fields=["renewal_state", "updated_at"])
                graced += 1
        else:
            with transaction.atomic():
                sub.status = "expired"
                sub.plan = "free"
                sub.renewal_state = "not_due"
                sub.save(update_fields=["status", "plan", "renewal_state", "updated_at"])
                _wallet(sub.user).reset_subscription(0)
            expired += 1
    return f"cancelled {cancelled}, graced {graced}, expired {expired}"


@shared_task
def expire_pack_credits():
    """Pack lots past their 12-month expiry with credits left → zero them out,
    logging a pack_expiry ledger row and decrementing the wallet cache. Idempotent:
    the filter excludes already-drained lots."""
    from .models import CreditLedger, CreditWallet, PackCreditLot

    now = timezone.now()
    count = 0
    qs = PackCreditLot.objects.filter(expires_at__lt=now, credits_remaining__gt=0)
    for lot_id in list(qs.values_list("id", flat=True)):
        with transaction.atomic():
            lot = PackCreditLot.objects.select_for_update().get(pk=lot_id)
            if lot.credits_remaining <= 0:
                continue
            wallet = CreditWallet.objects.select_for_update().get(pk=lot.wallet_id)
            amount = lot.credits_remaining
            lot.credits_remaining = 0
            lot.save(update_fields=["credits_remaining"])
            wallet.pack_balance = max(0, wallet.pack_balance - amount)
            wallet.save(update_fields=["pack_balance", "updated_at"])
            CreditLedger.objects.create(
                user_id=lot.user_id,
                delta=-amount,
                bucket="pack",
                reason="pack_expiry",
                operation="",
                tokens=0,
                balance_after=wallet.pack_balance,
            )
        count += 1
    return f"expired {count} pack lots"
