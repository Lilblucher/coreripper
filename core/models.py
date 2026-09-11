from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Tool(models.Model):
    CATEGORY_CHOICES = [
        ("dev-tools", "Developer Tools"),
        ("ai-tools", "AI Tools"),
        ("network-tools", "Network Tools"),
    ]
    STATUS_CHOICES = [
        ("operational", "Operational"),
        ("degraded", "Degraded"),
        ("down", "Down"),
    ]
    TIER_CHOICES = [
        ("local", "Local (free-tier eligible)"),
        ("api", "API (Premium only)"),
    ]

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    path = models.CharField(
        max_length=200, blank=True, help_text="Path relative to frontend/, e.g. dev-tools/json_formatter.html"
    )
    # Backend dispatch key from /api/toolbox/?tool=…  how the access gate maps a
    # request to this row's tier. Blank for frontend-only tools (dev tools,
    # calculators) that never hit the server, so can't be gated server-side.
    tool_key = models.CharField(
        max_length=50, blank=True,
        help_text="Backend dispatch key used in /api/toolbox/?tool=… . Blank for frontend-only tools.",
    )
    # Access tier: 'local' tools are free-tier eligible (Guest trial + Free quota),
    # 'api' tools are Premium-only (Guests still get their 3-op trial). Admin-editable.
    tier = models.CharField(max_length=10, choices=TIER_CHOICES, default="local")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="operational")
    notes = models.TextField(blank=True, help_text="Admin-only notes, e.g. what's currently wrong")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.category}-{self.name}")
        super().save(*args, **kwargs)


class SubnetDrillStreak(models.Model):
    """Per-user practice streak for the Subnet & CIDR drill trainer.

    A calendar-day streak (not session-based)  a retention/virality hook,
    not a paywall feature, so it's available to every logged-in user (Free
    included). Logged once per completed drill session via
    /api/core/subnet-streak/log/; the increment/reset logic lives in the
    view, keyed off last_practiced_date vs "today".
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subnet_drill_streak"
    )
    current_streak_days = models.IntegerField(default=0)
    longest_streak_days = models.IntegerField(default=0)
    last_practiced_date = models.DateField(null=True, blank=True)
    total_problems_solved = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user}  {self.current_streak_days}d streak, {self.total_problems_solved} solved"


class CategoryImage(models.Model):
    """One real, freely-licensed Wikimedia Commons photo in a per-(app,
    category) pool, fetched by core.commons_images + the
    fetch_category_images management command  never a fabricated image.
    news/hardware list + detail views pick one deterministically per
    article (hash of the article id) so the same article always shows the
    same photo, and the pool gives real variety across a category's cards
    and its "Featured" slideshow. An empty pool (fetch failed or nothing
    matched) is an honest gap  the frontend falls back to its existing
    category icon block, never a fake image.
    """
    APP_CHOICES = [("news", "News"), ("hardware", "Hardware")]

    app = models.CharField(max_length=20, choices=APP_CHOICES)
    category = models.CharField(max_length=40)
    image_url = models.URLField(max_length=500)
    thumb_url = models.URLField(max_length=500)
    credit_name = models.CharField(max_length=255, blank=True)
    credit_url = models.URLField(max_length=500, blank=True)
    license_name = models.CharField(max_length=100, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["app", "category", "id"]
        unique_together = [("app", "category", "image_url")]

    def __str__(self):
        return f"{self.app}/{self.category}: {self.image_url}"


class FeatureFlag(models.Model):
    """A sitewide kill-switch for one CoreRipper feature, flipped from the
    admin engine room. Enforcement is real, not cosmetic: core.middleware.
    FeatureFlagMiddleware maps API path prefixes to these keys and returns
    503 feature_disabled when a switch is off. Admin/auth endpoints are never
    gated so a superuser can't lock themselves out of the cockpit."""

    key = models.SlugField(max_length=50, unique=True)
    label = models.CharField(max_length=100)
    description = models.CharField(max_length=250, blank=True)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        state = "ON" if self.enabled else "OFF"
        return f"{self.label} [{state}]"
