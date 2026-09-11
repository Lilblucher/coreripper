"""Usage-cost guardrails for premium AI tool calls.

Two independent limits, both required by the implementation spec (sections 3 and 10):

1. Per-user monthly cap  protects the margin on a single subscriber. Set well below
   the subscription price so a $12/month plan can never rack up more than a few dollars
   of API cost even under heavy use.
2. Global daily budget kill-switch  protects the business from a runaway bill (bug,
   abuse, a viral spike) regardless of how many individual users are still under their
   personal cap.

Both read their ceilings from env vars so they can be tuned without a deploy.
"""
import os
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from accounts.models import UsageLog

# ~30-40% of a $12/month Premium plan, per the spec's fair-use guidance.
PREMIUM_MONTHLY_CAP_USD = Decimal(os.environ.get("PREMIUM_MONTHLY_CAP_USD", "4.20"))

# Total spend allowed across ALL users, ALL tools, per rolling 24h window.
GLOBAL_DAILY_BUDGET_USD = Decimal(os.environ.get("GLOBAL_DAILY_BUDGET_USD", "10.00"))


def _current_billing_period_start(now=None):
    """Calendar-month billing period. Simple and predictable; swap for a rolling
    30-day-from-subscription-start window later if that turns out to matter."""
    now = now or timezone.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def user_month_spend(user, now=None):
    period_start = _current_billing_period_start(now)
    total = UsageLog.objects.filter(user=user, created_at__gte=period_start).aggregate(
        total=Sum("est_cost_usd")
    )["total"]
    return total or Decimal("0")


def check_user_quota(user, now=None):
    """Returns (allowed: bool, used: Decimal, cap: Decimal)."""
    used = user_month_spend(user, now=now)
    return used < PREMIUM_MONTHLY_CAP_USD, used, PREMIUM_MONTHLY_CAP_USD


def global_day_spend(now=None):
    now = now or timezone.now()
    window_start = now - timedelta(hours=24)
    total = UsageLog.objects.filter(created_at__gte=window_start).aggregate(
        total=Sum("est_cost_usd")
    )["total"]
    return total or Decimal("0")


def check_global_budget(now=None):
    """Returns (allowed: bool, used: Decimal, cap: Decimal). When this trips, every
    premium endpoint should show the 'premium tools are resting, back tomorrow'
    message rather than let the bill run  see spec section 10."""
    used = global_day_spend(now=now)
    return used < GLOBAL_DAILY_BUDGET_USD, used, GLOBAL_DAILY_BUDGET_USD
