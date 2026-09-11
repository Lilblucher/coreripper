"""Server-side pricing for Premium subscriptions.

The admin (superuser) manages PlanPrice rows from the Engine Room's Pricing tab;
the public pricing page and billing page render whatever is active here. The
charge flow accepts only a price_id  the amount charged is always resolved from
this table server-side, never taken from the client.

Currency policy: the admin sets prices in USD only. Zambian customers are
charged the Kwacha equivalent at the real-time USD→ZMW market rate (see
payments/fx.py); international card customers are charged the USD amount as-is.
"""
from django.db import models


class PlanPrice(models.Model):
    # "premium" retained (legacy) so the already-seeded row stays valid; it maps
    # to "pro" at settlement. New prices use lite/standard/pro.
    PLAN_CHOICES = [
        ("lite", "Lite"),
        ("standard", "Standard"),
        ("pro", "Pro"),
        ("premium", "Premium (legacy)"),
    ]

    label = models.CharField(max_length=80)  # e.g. "Pro Monthly"
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default="pro")
    display_amount_usd = models.DecimalField(max_digits=8, decimal_places=2)
    period_days = models.PositiveIntegerField(default=30)  # 30 = monthly, 365 = annual
    is_active = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        state = "active" if self.is_active else "inactive"
        return f"{self.label} · ${self.display_amount_usd} · {self.period_days}d ({state})"


class CreditPackPrice(models.Model):
    """One-time Claude-credit packs (Phase 4 of the monetization plan). Same
    server-side-amounts-only policy as PlanPrice: the client sends a pack_id,
    never an amount, and the USD price here is the single source of truth.
    Settlement grants `credits` via CreditWallet.grant_pack() (12-month lot
    expiry) instead of extending a subscription."""

    label = models.CharField(max_length=80)  # e.g. "Starter"
    credits = models.PositiveIntegerField()
    display_amount_usd = models.DecimalField(max_digits=8, decimal_places=2)
    is_active = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        state = "active" if self.is_active else "inactive"
        return f"{self.label} · {self.credits} credits · ${self.display_amount_usd} ({state})"


class FxRate(models.Model):
    """Last successfully fetched exchange rate per pair  the offline/outage
    fallback for payments/fx.py. One row per pair, updated in place on every
    live fetch, so a deployed site that loses internet keeps charging at the
    most recent real rate instead of a stale hardcoded one."""

    pair = models.CharField(max_length=7, unique=True)  # "USD/ZMW"
    rate = models.DecimalField(max_digits=12, decimal_places=6)
    source = models.CharField(max_length=200, blank=True)  # provider URL
    fetched_at = models.DateTimeField()

    def __str__(self):
        return f"{self.pair} = {self.rate} ({self.fetched_at:%Y-%m-%d %H:%M})"
