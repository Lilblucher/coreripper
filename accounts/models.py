import secrets

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


class Subscription(models.Model):
    # Four tiers (monetization rework). "premium" is retained as a legacy value
    # only so historical rows/prices stay valid  new plans are free/lite/standard/pro.
    PLAN_CHOICES = [
        ("free", "Free"),
        ("lite", "Lite"),
        ("standard", "Standard"),
        ("pro", "Pro"),
        ("premium", "Premium (legacy)"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("trialing", "Trialing"),
        ("cancelled", "Cancelled"),
        ("expired", "Expired"),
    ]
    RENEWAL_CHOICES = [
        ("not_due", "Not due"),
        ("awaiting_payment", "Awaiting payment"),
        ("grace", "Grace"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default="free")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="expired")
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    renewal_state = models.CharField(max_length=20, choices=RENEWAL_CHOICES, default="not_due")
    # Deprecated: dual-written with current_period_end during the transition
    # (receipt email, admin serializer, and payments tests still read it).
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} ({self.plan}/{self.status})"

    @property
    def is_premium(self):
        """Back-compat shim so @premium_required, get_access_tier, monitors, and
        has_active_paid_subscription keep working unchanged in Phase 1: "has any
        paid-tier access right now". Phase 2 replaces the call sites with
        @requires_tier. Lazy expiry applies to TRIALS ONLY  paid expiry runs
        through the beat pipeline because of the 3-day grace window, which a lazy
        read must not skip."""
        if self.status not in ("active", "trialing") or self.plan == "free":
            return False
        if self.status == "trialing" and self.current_period_end and self.current_period_end < timezone.now():
            self.status = "expired"
            self.plan = "free"
            self.save(update_fields=["status", "plan", "updated_at"])
            return False
        return True

    @property
    def is_trial(self):
        return self.status == "trialing" and self.is_premium

    @property
    def trial_days_remaining(self):
        # Ceils to whole days so a freshly-started 3-day trial reads "3 days left"
        # rather than "2" (a floor would show 2 immediately, since remaining is
        # 2d 23h 59m 59s at t=0). Hits 0 only in the last hour before expiry.
        if not self.is_trial:
            return None
        end = self.current_period_end or self.expires_at
        if end is None:
            return None
        remaining = end - timezone.now()
        if remaining.total_seconds() <= 0:
            return 0
        return -(-int(remaining.total_seconds()) // 86400)


class UsageLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="usage"
    )
    tool = models.CharField(max_length=64)  # e.g. "feedback_tutor", "quiz_generator"
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    est_cost_usd = models.DecimalField(max_digits=8, decimal_places=6, default=0)
    cache_hit = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user} · {self.tool} · ${self.est_cost_usd}"


class Payment(models.Model):
    STATUS_CHOICES = [("pending", "Pending"), ("paid", "Paid"), ("failed", "Failed")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments"
    )
    provider = models.CharField(max_length=32, default="stub")
    provider_ref = models.CharField(max_length=128, blank=True)
    # amount/currency/period_days are snapshots taken from the PlanPrice at
    # charge time  editing a price later never rewrites payment history.
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default="ZMW")
    method = models.CharField(max_length=32, blank=True)  # mtn_momo | airtel_money | card
    period_days = models.PositiveIntegerField(default=30)
    price = models.ForeignKey(
        "payments.PlanPrice", null=True, blank=True, on_delete=models.SET_NULL, related_name="payments"
    )
    # Credit-pack purchases (Phase 4): exactly one of price/pack is set per
    # payment. credits_amount is a snapshot like amount/currency  editing the
    # pack later never rewrites what a past purchase granted.
    pack = models.ForeignKey(
        "payments.CreditPackPrice", null=True, blank=True, on_delete=models.SET_NULL, related_name="payments"
    )
    credits_amount = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="pending")
    # Stamped by the one caller that wins the pending→paid transition
    # (accounts.subscription_utils.settle_payment)  audit trail for when
    # Premium was actually granted off this payment.
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} · {self.amount} {self.currency} · {self.status}"


class Profile(models.Model):
    """Extra account fields with no home on Django's built-in User model.
    first_name/last_name already exist on User itself and are used directly 
    this only holds fields that don't."""

    MODEL_CHOICES = [("groq", "Groq"), ("gemini", "Gemini"), ("claude", "Claude")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    company = models.CharField(max_length=120, blank=True)
    title = models.CharField(max_length=120, blank=True)
    phone_dial_code = models.CharField(max_length=6, blank=True)
    phone_national = models.CharField(max_length=20, blank=True)
    timezone = models.CharField(max_length=32, blank=True, default="UTC+0")
    # AI model switcher preference (defaults to a free model  Claude is always
    # opt-in so credits only ever burn deliberately).
    preferred_model = models.CharField(max_length=16, choices=MODEL_CHOICES, default="groq")
    # Records email verification (new signups) and the consent-policy version the
    # user last accepted (Phase 3 cookie banner).
    email_verified = models.BooleanField(default=False)
    cookie_consent_version = models.CharField(max_length=16, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"profile for {self.user}"


class NotificationPreference(models.Model):
    """Account-wide notification toggles. email_alerts/whatsapp_alerts are
    real gates, not cosmetic  monitors/tasks.py checks these alongside each
    Monitor's own alert_email/alert_whatsapp flag, so both must be on for a
    channel to actually fire. product_updates gates the weekly newsletter
    (accounts.tasks.send_newsletter, Fridays 09:00 UTC)  latest published
    blog articles + approved news items, members-only by construction since
    this flag only exists on a logged-in User's own preferences row."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_prefs"
    )
    email_alerts = models.BooleanField(default=True)
    whatsapp_alerts = models.BooleanField(default=True)
    weekly_digest = models.BooleanField(default=False)
    product_updates = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"notification prefs for {self.user}"


class SupportTicket(models.Model):
    CATEGORY_CHOICES = [
        ("technical", "Technical Issue"),
        ("billing", "Billing"),
        ("account", "Account"),
        ("feature", "Feature Request"),
        ("other", "Other"),
    ]
    STATUS_CHOICES = [("open", "Open"), ("closed", "Closed")]

    # Guests can submit support tickets (see support_ticket_view). For a guest
    # the row records the submitter details on the ticket itself (first_name/
    # last_name/email) and this FK is left null.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_tickets",
        null=True, blank=True,
    )
    ticket_id = models.CharField(max_length=16, unique=True, editable=False)
    first_name = models.CharField(max_length=80, blank=True)
    last_name = models.CharField(max_length=80, blank=True)
    email = models.EmailField()
    domain_or_ip = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.TextField(max_length=2000)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.ticket_id:
            self.ticket_id = f"CR-{secrets.randbelow(900000) + 100000}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ticket_id} ({self.status})"


class SupportTicketAttachment(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="support_attachments/%Y/%m/")
    original_name = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_name


class AuthToken(models.Model):
    """One bearer token per LOGIN, not per user  the auth mechanism for the
    whole site. A user can hold multiple tokens at once (one per device/
    browser they're logged in on); lookup is always by `key` (unique), which
    is why switching this from OneToOneField to ForeignKey on 2026-07-16
    (to support settings.html's real "Active Sessions" list + revoke) needed
    no change to TokenAuthMiddleware at all  it never used the reverse
    `user.auth_token` accessor, only `AuthToken.objects.filter(key=...)`.

    A user is an admin purely by `user.is_staff`; there's no separate admin
    login or admin-only token. Bearer tokens (not session cookies) because the
    static frontend runs on its own dev server, so cross-origin session
    cookies aren't reliable.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="auth_tokens")
    key = models.CharField(max_length=64, unique=True, editable=False)
    device_label = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    # Access tokens expire (AUTH_TOKEN_LIFETIME_HOURS); a null expiry means
    # "never" and only exists for rows predating the expiry migration's
    # backfill  new tokens always get one (see accounts.views._issue_token).
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = secrets.token_hex(32)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at <= timezone.now()

    def __str__(self):
        return f"token for {self.user}"


class RefreshToken(models.Model):
    """Long-lived "Remember Me" credential, opt-in at login  without it a
    session simply lapses when its AuthToken expires. The raw token is handed
    to the client exactly once; only its SHA-256 is stored, so a DB leak can't
    be replayed. Rotated on every use (accounts.views.refresh_view revokes the
    row and issues a successor in the same transaction), and CASCADE-tied to
    its AuthToken device row so revoking a session from settings.html's Active
    Sessions list also kills the ability to silently resurrect it."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="refresh_tokens"
    )
    auth_token = models.ForeignKey(AuthToken, on_delete=models.CASCADE, related_name="refresh_tokens")
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    device_label = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)

    @staticmethod
    def hash_raw(raw):
        import hashlib

        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, user, auth_token, request=None):
        """Create a row and return the RAW token  the only moment it exists
        server-side in the clear."""
        raw = secrets.token_hex(32)
        ip_address = request.META.get("REMOTE_ADDR") or None if request is not None else None
        cls.objects.create(
            user=user,
            auth_token=auth_token,
            token_hash=cls.hash_raw(raw),
            device_label=auth_token.device_label,
            ip_address=ip_address,
            expires_at=timezone.now() + timezone.timedelta(days=settings.REFRESH_TOKEN_LIFETIME_DAYS),
        )
        return raw

    @property
    def is_valid(self):
        return not self.revoked and self.expires_at > timezone.now()

    def __str__(self):
        return f"refresh token for {self.user} ({'revoked' if self.revoked else 'active'})"


class PasswordResetToken(models.Model):
    """A one-time-use 6-digit code emailed to a user to authorize a password
    reset (OTP-style, not a clickable link).

    Not a session/cookie mechanism  matches the rest of this app's
    bearer-token-only approach. Expiry is checked against `created_at` at
    validation time (see accounts.views.reset_password_view) rather than
    stored as a separate field. Lookups are always scoped by
    `(user, token)` together (see reset_password_view), so the code itself
    doesn't need to be globally unique  a 6-digit keyspace is small enough
    that `attempts` also caps brute-force guesses against any one code.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="password_reset_tokens"
    )
    token = models.CharField(max_length=10, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = f"{secrets.randbelow(1_000_000):06d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"reset token for {self.user} ({'used' if self.used else 'active'})"


class EmailVerificationToken(models.Model):
    """A one-time-use 6-digit code emailed at signup to verify the address before
    the account is activated. Parallel shape to PasswordResetToken (mirror, don't
    genericize  same pattern the content apps follow) so the two flows never
    share a table. Same expiry/attempts/single-use semantics; see
    accounts.views.verify_email_view."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_verification_tokens"
    )
    token = models.CharField(max_length=10, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = f"{secrets.randbelow(1_000_000):06d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"verification token for {self.user} ({'used' if self.used else 'active'})"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_free_subscription(sender, instance, created, **kwargs):
    """Every new user starts on the free plan so request.user.subscription never
    needs a null-check  is_premium simply evaluates False until they pay.
    Same reasoning extended to Profile/NotificationPreference: every read/write
    of request.user.profile or request.user.notification_prefs can assume the
    row exists, no get-or-create scattered across every view that touches it."""
    if created:
        Subscription.objects.get_or_create(user=instance)
        Profile.objects.get_or_create(user=instance)
        NotificationPreference.objects.get_or_create(user=instance)
