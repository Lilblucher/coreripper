"""Payment settlement + Premium activation, shared by every path that can
confirm a payment: the verify-polling endpoint, the Lenco webhook, the OTP
endpoint, and the manual Django-admin action (soft-launch flow).

The core guarantee is idempotency: settle_payment() flips a Payment
pending→paid with a single atomic conditional UPDATE, so however many callers
race (duplicate webhooks, a webhook and a poller, an admin double-click), only
one ever wins the transition and Premium is extended exactly once.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import Payment, Subscription


# Maps a PlanPrice.plan (incl. the legacy "premium") onto a Subscription tier.
_PRICE_PLAN_TO_TIER = {"lite": "lite", "standard": "standard", "pro": "pro", "premium": "pro"}


def activate_subscription(user, days, tier="pro"):
    """Grant/extend a paid subscription: extend from the current period end if
    the user is still premium, otherwise start a fresh period from now (same
    stacking behavior the Django-admin action always had). Refreshes the tier's
    monthly Claude-credit grant.

    credits is imported lazily so app-loading order never trips over it and so
    accounts has no hard import dependency on the credits app."""
    subscription, _ = Subscription.objects.get_or_create(user=user)
    now = timezone.now()
    base = (
        subscription.current_period_end
        if (subscription.is_premium and subscription.current_period_end)
        else now
    )
    end = base + timedelta(days=days)
    subscription.plan = tier
    subscription.status = "active"
    subscription.renewal_state = "not_due"
    subscription.cancel_at_period_end = False
    subscription.current_period_start = now
    subscription.current_period_end = end
    subscription.expires_at = end  # dual-write during the transition
    subscription.save(
        update_fields=[
            "plan",
            "status",
            "renewal_state",
            "cancel_at_period_end",
            "current_period_start",
            "current_period_end",
            "expires_at",
            "updated_at",
        ]
    )

    from django.conf import settings as _settings
    from credits.models import CreditWallet

    grant = _settings.TIER_MONTHLY_CREDITS.get(tier, 0)
    wallet, _ = CreditWallet.objects.get_or_create(user=user)
    wallet.reset_subscription(grant)
    return subscription


# Back-compat alias: existing call sites that grant "Premium" now grant the pro tier.
def activate_premium(user, days):
    return activate_subscription(user, days, tier="pro")


def settle_payment(payment_id):
    """Idempotent pending→paid transition + Premium activation + receipt email.

    Returns True only for the single caller that wins the transition; every
    other caller (duplicate webhook, concurrent poll, repeated admin action)
    gets False and changes nothing.
    """
    now = timezone.now()
    updated = Payment.objects.filter(pk=payment_id, status="pending").update(
        status="paid", activated_at=now, updated_at=now
    )
    if not updated:
        return False

    payment = Payment.objects.select_related("user", "price", "pack").get(pk=payment_id)
    if payment.pack_id or payment.credits_amount:
        # Credit-pack purchase: grant a 12-month pack lot instead of touching
        # the subscription. grant_pack writes its own ledger row atomically.
        from credits.models import CreditWallet

        wallet, _ = CreditWallet.objects.get_or_create(user=payment.user)
        wallet.grant_pack(payment.credits_amount, purchase_ref=payment.provider_ref)
    else:
        tier = _PRICE_PLAN_TO_TIER.get(payment.price.plan, "pro") if payment.price else "pro"
        activate_subscription(payment.user, payment.period_days or 30, tier=tier)
    try:
        send_payment_receipt(payment)
    except Exception as exc:
        # A receipt that fails to send must never un-pay a payment.
        print(f"[payments] receipt email failed for payment {payment.pk}: {exc}")
    return True


def mark_payment_failed(payment_id):
    """Idempotent pending→failed; a payment already settled stays paid."""
    return bool(
        Payment.objects.filter(pk=payment_id, status="pending").update(
            status="failed", updated_at=timezone.now()
        )
    )


def send_payment_receipt(payment):
    """Email the payer a receipt from the billing address (replies land in the
    billing inbox via Cloudflare routing), with a branded PDF invoice attached.

    The PDF is the artifact a customer actually keeps - it's what gets filed for
    expenses or forwarded to an accountant - so the email body is deliberately a
    short confirmation rather than a duplicate of it. If PDF rendering fails for
    any reason the email still goes out unattached: a receipt that arrives
    without its invoice is a far smaller failure than one that never arrives.
    """
    from django.core.mail import EmailMessage

    is_pack = bool(payment.pack_id or payment.credits_amount)
    priced = payment.pack if is_pack else payment.price
    if is_pack:
        label = f"{payment.pack.label} credit pack" if payment.pack else "Sonnet-5 credit pack"
        label += f" ({payment.credits_amount} credits)"
    else:
        label = payment.price.label if payment.price else "Premium"
    if payment.currency == "USD":
        amount_line = f"${payment.amount} USD"
    else:
        usd = f" (list price ${priced.display_amount_usd} USD)" if priced else ""
        amount_line = f"K{payment.amount} {payment.currency}{usd}"
    subscription = getattr(payment.user, "subscription", None)
    period_end = (
        subscription.current_period_end or subscription.expires_at if subscription else None
    )
    method_names = {"mtn_momo": "MTN Mobile Money", "airtel_money": "Airtel Money", "card": "Card"}
    method = method_names.get(payment.method, payment.method or payment.provider)

    if is_pack:
        outcome_line = (
            f"{payment.credits_amount} Sonnet-5 credits have been added to your wallet. "
            "They are spent only when you select the Sonnet-5 model, and remain valid "
            "for 12 months."
        )
    else:
        until = f" and runs until {period_end.strftime('%d %b %Y')}" if period_end else ""
        outcome_line = f"Your {label} subscription is active{until}."

    from core.pdf import build_invoice_pdf, invoice_number

    ref = invoice_number(payment)
    body = (
        f"Hello{' ' + payment.user.first_name if payment.user.first_name else ''},\n\n"
        "Thank you for your payment. This is confirmation that it went through "
        "successfully.\n\n"
        f"Invoice     {ref}\n"
        f"Item        {label}\n"
        f"Amount      {amount_line}\n"
        f"Paid via    {method}\n"
        f"Reference   {payment.provider_ref or '-'}\n\n"
        f"{outcome_line}\n\n"
        "Your full invoice is attached as a PDF, and every invoice on your account "
        "is available any time from your Billing page.\n\n"
        "If anything here looks wrong, reply to this email and we'll sort it out.\n\n"
        "CoreRipper Billing"
    )

    message = EmailMessage(
        subject=f"Payment receipt {ref} - CoreRipper",
        body=body,
        from_email=settings.EMAIL_FROM_BILLING,
        to=[payment.user.email],
    )
    try:
        message.attach(f"CoreRipper-invoice-{ref}.pdf", build_invoice_pdf(payment), "application/pdf")
    except Exception as exc:
        print(f"[send_payment_receipt] invoice PDF failed for payment {payment.pk}: {exc}")
    message.send(fail_silently=False)


def has_active_paid_subscription(user):
    """True when the user's current Premium came from a real settled payment 
    used by the Engine Room to lock the manual plan dropdown for paying
    subscribers. Lifts automatically once the paid period expires (is_premium
    lazily flips false), so lapsed users can be managed manually again."""
    subscription = getattr(user, "subscription", None)
    if not (subscription and subscription.is_premium):
        return False
    # Pack purchases are excluded: buying credits during a trial must not lock
    # the Engine Room plan dropdown  only real subscription payments do.
    return user.payments.filter(
        status="paid", activated_at__isnull=False, pack__isnull=True, credits_amount=0
    ).exists()
