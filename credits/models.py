"""Credit economy: one wallet per user, an append-only ledger, per-purchase
pack lots (so packs can expire on their own 12-month clock), and a usage record
for every AI call.

Everything that mutates a wallet does so inside a single transaction that also
writes the ledger row(s), under a row lock, so the ledger is always a faithful
replay of the wallet. `reconcile_credit_wallets` rebuilds wallets from the
ledger to prove that invariant.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone


class InsufficientCredits(Exception):
    """Raised by CreditWallet.spend() when total balance can't cover the charge."""


class ClaudeUnavailable(Exception):
    """Raised by credits.services.run_ai() when the Sonnet-5 path is requested
    while the `claude_ai` feature flag is off (Anthropic credits not funded yet).

    Distinct from InsufficientCredits: nothing is wrong with the user's wallet,
    the whole capability is switched off site-wide, so the honest answer is "not
    available yet", not "buy more credits". Callers surface it as a 503."""


def _now():
    return timezone.now()


class CreditWallet(models.Model):
    """Two balances, one visible total. `subscription_balance` resets each cycle;
    `pack_balance` is a maintained cache of the sum of unexpired PackCreditLot
    `credits_remaining` (per-purchase truth lives on the lots so packs can expire
    individually)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credit_wallet"
    )
    subscription_balance = models.PositiveIntegerField(default=0)
    pack_balance = models.PositiveIntegerField(default=0)
    # Guards monthly_refresh idempotency  the daily beat task only re-grants
    # subscription credits when this is null or older than ~30 days.
    last_refresh_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"wallet<{self.user}> sub={self.subscription_balance} pack={self.pack_balance}"

    @property
    def total_balance(self):
        return self.subscription_balance + self.pack_balance

    # -- internal helpers (assume the caller already holds the row lock) --

    def _write_ledger(self, *, delta, bucket, reason, operation, tokens, balance_after):
        CreditLedger.objects.create(
            user_id=self.user_id,
            delta=delta,
            bucket=bucket,
            reason=reason,
            operation=operation,
            tokens=tokens,
            balance_after=balance_after,
        )

    def _consume_pack_lots(self, amount, *, operation, tokens, reason="spend"):
        """Drain `amount` from pack lots, earliest-expiry-first. Assumes the row
        lock is held and `amount` <= pack_balance. Writes one ledger row per lot
        touched and keeps pack_balance in sync."""
        remaining = amount
        lots = (
            PackCreditLot.objects.select_for_update()
            .filter(wallet=self, credits_remaining__gt=0)
            .order_by("expires_at", "id")
        )
        for lot in lots:
            if remaining <= 0:
                break
            take = min(lot.credits_remaining, remaining)
            lot.credits_remaining -= take
            lot.save(update_fields=["credits_remaining"])
            self.pack_balance -= take
            remaining -= take
            self._write_ledger(
                delta=-take,
                bucket="pack",
                reason=reason,
                operation=operation,
                tokens=tokens,
                balance_after=self.pack_balance,
            )

    def spend(self, amount, *, reason="spend", operation="", tokens=0):
        """Spend `amount` credits: subscription bucket first, then pack lots
        (earliest-expiry-first). Raises InsufficientCredits (mutating nothing) if
        the total balance can't cover it. Returns the amount spent."""
        if amount <= 0:
            return 0
        with transaction.atomic():
            w = CreditWallet.objects.select_for_update().get(pk=self.pk)
            if w.total_balance < amount:
                raise InsufficientCredits(
                    f"need {amount}, have {w.total_balance}"
                )
            remaining = amount
            if w.subscription_balance > 0:
                take = min(w.subscription_balance, remaining)
                w.subscription_balance -= take
                remaining -= take
                w._write_ledger(
                    delta=-take,
                    bucket="subscription",
                    reason=reason,
                    operation=operation,
                    tokens=tokens,
                    balance_after=w.subscription_balance,
                )
            if remaining > 0:
                w._consume_pack_lots(remaining, operation=operation, tokens=tokens, reason=reason)
            w.save(update_fields=["subscription_balance", "pack_balance", "updated_at"])
            # keep the caller's in-memory copy consistent
            self.subscription_balance = w.subscription_balance
            self.pack_balance = w.pack_balance
            return amount

    def charge_actual(self, amount, *, operation="", tokens=0):
        """Like spend() but clamps to the available balance instead of raising 
        used post-hoc for the actual Claude token charge. Never goes negative.
        Returns the amount actually charged (may be less than `amount`)."""
        if amount <= 0:
            return 0
        with transaction.atomic():
            w = CreditWallet.objects.select_for_update().get(pk=self.pk)
            charge = min(amount, w.total_balance)
            if charge <= 0:
                return 0
            remaining = charge
            if w.subscription_balance > 0:
                take = min(w.subscription_balance, remaining)
                w.subscription_balance -= take
                remaining -= take
                w._write_ledger(
                    delta=-take,
                    bucket="subscription",
                    reason="spend",
                    operation=operation,
                    tokens=tokens,
                    balance_after=w.subscription_balance,
                )
            if remaining > 0:
                w._consume_pack_lots(remaining, operation=operation, tokens=tokens)
            w.save(update_fields=["subscription_balance", "pack_balance", "updated_at"])
            self.subscription_balance = w.subscription_balance
            self.pack_balance = w.pack_balance
            return charge

    def grant(self, bucket, amount, reason):
        """Add `amount` credits to a bucket (subscription grants only  packs go
        through grant_pack so they get a lot with an expiry)."""
        if amount <= 0:
            return
        assert bucket == "subscription", "use grant_pack() for pack credits"
        with transaction.atomic():
            w = CreditWallet.objects.select_for_update().get(pk=self.pk)
            w.subscription_balance += amount
            w._write_ledger(
                delta=amount,
                bucket="subscription",
                reason=reason,
                operation="",
                tokens=0,
                balance_after=w.subscription_balance,
            )
            w.save(update_fields=["subscription_balance", "updated_at"])
            self.subscription_balance = w.subscription_balance

    def grant_pack(self, amount, *, expires_at=None, reason="pack_purchase", purchase_ref=""):
        """Create a PackCreditLot (default expiry now + PACK_CREDIT_LIFETIME_DAYS)
        and bump the pack_balance cache. Phase 4's pack checkout calls this on
        settlement; Phase 1 ships it so packs never need a schema rework."""
        if amount <= 0:
            return None
        if expires_at is None:
            days = getattr(settings, "PACK_CREDIT_LIFETIME_DAYS", 365)
            expires_at = _now() + timezone.timedelta(days=days)
        with transaction.atomic():
            w = CreditWallet.objects.select_for_update().get(pk=self.pk)
            lot = PackCreditLot.objects.create(
                user_id=w.user_id,
                wallet=w,
                credits_granted=amount,
                credits_remaining=amount,
                expires_at=expires_at,
                purchase_ref=purchase_ref,
            )
            w.pack_balance += amount
            w._write_ledger(
                delta=amount,
                bucket="pack",
                reason=reason,
                operation="",
                tokens=0,
                balance_after=w.pack_balance,
            )
            w.save(update_fields=["pack_balance", "updated_at"])
            self.pack_balance = w.pack_balance
            return lot

    def reset_subscription(self, amount, *, stamp_refresh=True):
        """Zero the subscription bucket (logging an expiry_reset row for any
        leftover), then grant `amount` fresh subscription credits (monthly_refresh).
        Used on renewal/settlement and by the daily refresh task. Pack credits are
        untouched."""
        with transaction.atomic():
            w = CreditWallet.objects.select_for_update().get(pk=self.pk)
            if w.subscription_balance > 0:
                old = w.subscription_balance
                w.subscription_balance = 0
                w._write_ledger(
                    delta=-old,
                    bucket="subscription",
                    reason="expiry_reset",
                    operation="",
                    tokens=0,
                    balance_after=0,
                )
            if amount > 0:
                w.subscription_balance = amount
                w._write_ledger(
                    delta=amount,
                    bucket="subscription",
                    reason="monthly_refresh",
                    operation="",
                    tokens=0,
                    balance_after=amount,
                )
            if stamp_refresh:
                w.last_refresh_at = _now()
            w.save(update_fields=["subscription_balance", "last_refresh_at", "updated_at"])
            self.subscription_balance = w.subscription_balance
            self.last_refresh_at = w.last_refresh_at


class PackCreditLot(models.Model):
    """One row per credit-pack ("boost") purchase. Pack credits expire per
    purchase on a 12-month clock (user override of the doc's "never expire"),
    which is why per-lot tracking exists rather than a single pack counter."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pack_credit_lots"
    )
    wallet = models.ForeignKey(
        CreditWallet, on_delete=models.CASCADE, related_name="pack_lots"
    )
    credits_granted = models.PositiveIntegerField()
    credits_remaining = models.PositiveIntegerField()
    expires_at = models.DateTimeField()
    purchase_ref = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "expires_at"])]

    def __str__(self):
        return f"lot<{self.user}> {self.credits_remaining}/{self.credits_granted} exp {self.expires_at:%Y-%m-%d}"


class CreditLedger(models.Model):
    """Append-only. Every wallet mutation writes exactly one row per bucket
    touched, in the same transaction as the mutation. `balance_after` is the
    affected bucket's balance after this row was applied."""

    REASON_CHOICES = [
        ("monthly_refresh", "Monthly refresh"),
        ("pack_purchase", "Pack purchase"),
        ("spend", "Spend"),
        ("expiry_reset", "Expiry reset"),
        ("pack_expiry", "Pack expiry"),
    ]
    BUCKET_CHOICES = [("subscription", "Subscription"), ("pack", "Pack")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credit_ledger"
    )
    delta = models.IntegerField()  # signed
    bucket = models.CharField(max_length=16, choices=BUCKET_CHOICES)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    operation = models.CharField(max_length=64, blank=True)
    tokens = models.PositiveIntegerField(default=0)
    balance_after = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "bucket"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("CreditLedger rows are append-only")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"ledger<{self.user}> {self.delta:+d} {self.bucket}/{self.reason}"


class AIUsageRecord(models.Model):
    """One row per AI call, all models (free ones at credits_charged=0), for
    capacity planning and calibrating the published credit estimates. user is
    nullable because news_draft runs with no user."""

    MODEL_CHOICES = [("groq", "Groq"), ("gemini", "Gemini"), ("claude", "Claude")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_usage",
    )
    operation = models.CharField(max_length=64)
    model = models.CharField(max_length=16, choices=MODEL_CHOICES)
    model_name = models.CharField(max_length=64, blank=True)  # exact provider string
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    est_cost_usd = models.DecimalField(max_digits=8, decimal_places=6, default=Decimal("0"))
    credits_charged = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["operation", "created_at"]),
        ]

    def __str__(self):
        return f"usage<{self.user}> {self.operation} {self.model} {self.credits_charged}cr"
