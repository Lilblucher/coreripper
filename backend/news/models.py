from django.db import models
from django.utils import timezone

from core.intel.models_mixin import IntelImageMixin


class NewsDraft(IntelImageMixin, models.Model):
    """A moderation-queue row: AI-drafted news item awaiting human review.
    Nothing here is ever public until status='published'  see
    news/views.py::news_feed_view, the only reader of published rows."""

    STATUS_CHOICES = [
        ("pending", "Pending Review"),
        ("published", "Published"),
        ("rejected", "Rejected"),
        ("archived", "Archived"),
    ]
    # Deliberately not scoped to dev/security/networking content only 
    # hardware/gaming/CPU/GPU categories can be added here later without any
    # other model or view change, per the "keep it generic and extensible"
    # call on the Knowledge Hub redesign. No hardware-specific fields exist
    # yet because no hardware content pipeline exists yet.
    CATEGORY_CHOICES = [
        ("networking", "Networking"),
        ("security", "Cybersecurity"),
        ("dev", "Developer"),
        ("ai", "AI & Productivity"),
        ("databases", "Databases"),
        ("linux", "Linux"),
    ]

    title = models.CharField(max_length=300)
    source_url = models.URLField(unique=True, max_length=500)
    source_name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    trending_score = models.FloatField(default=0)

    ai_summary = models.TextField(help_text="Short blurb for digest email + card preview")
    ai_draft_body = models.TextField(help_text="Full draft article body, original wording")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True, help_text="Stamped once, the first time this flips to published.")
    archived_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Stamped once by the weekly wrap-up (news.tasks.news_weekly_wrapup). "
                   "An archived article keeps its own detail page (SEO-indexable, never "
                   "deleted) but drops off the main feed/related-articles surfaces.",
    )

    class Meta:
        ordering = ["-trending_score", "-created_at"]

    def __str__(self):
        return f"[{self.status}] {self.title}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        # Auto-create the primary source from source_url/source_name so every
        # draft has at least one ArticleSource row without the caller (the
        # aggregator, a management command, a future test) needing to know
        # about this model. Additional sources can be attached later.
        if is_new and not self.sources.exists():
            ArticleSource.objects.create(
                article=self, url=self.source_url, name=self.source_name, is_primary=True, order=0,
            )

    @property
    def computed_reading_time(self):
        from core.reading_time import estimate_reading_minutes

        return estimate_reading_minutes(self.ai_draft_body)

    @property
    def is_human_reviewed(self):
        return self.reviewed_at is not None

    @property
    def last_updated_at(self):
        latest = self.updates.order_by("-created_at").first()
        return latest.created_at if latest else self.published_at

    def publish(self):
        """Flip to published, stamping published_at only the first time, and
        log a timeline entry  shared by the cockpit endpoint (news/admin_views.py)
        and Django's built-in /admin/ action (news/admin.py) so both paths stay
        in sync rather than duplicating this logic."""
        first_publish = self.published_at is None
        self.status = "published"
        self.reviewed_at = timezone.now()
        if first_publish:
            self.published_at = self.reviewed_at
        self.save()
        if first_publish:
            self.updates.create(kind="published", title="Article published")

    def reject(self):
        self.status = "rejected"
        self.reviewed_at = timezone.now()
        self.save()

    def archive(self):
        """Flips a published article to archived, stamping archived_at only
        the first time. Deliberately never deletes the row  its detail page
        (news_detail_view) keeps serving it after this so the URL stays
        indexable; only the main feed/related-articles queries (both
        hardcoded to status="published") stop surfacing it."""
        first_archive = self.archived_at is None
        self.status = "archived"
        if first_archive:
            self.archived_at = timezone.now()
        self.save()
        if first_archive:
            self.updates.create(kind="archived", title="Article archived off the main feed")


class ArticleSource(models.Model):
    """A trusted reference backing an article. Most articles have exactly
    one (the item the aggregator found), but the model supports several 
    e.g. a future auto-detection pass corroborating a story against a second
    outlet, without any schema change."""

    article = models.ForeignKey(NewsDraft, on_delete=models.CASCADE, related_name="sources")
    url = models.URLField(max_length=500)
    name = models.CharField(max_length=150)
    is_primary = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.name} ({self.article_id})"


class ArticleUpdate(models.Model):
    """One entry in an article's Knowledge Timeline / What's New feed. The
    'published' entry is created automatically (see NewsDraft.publish());
    everything else is logged by a superuser through the cockpit's News tab
    today. Generic on purpose  a future automated change-detection job can
    write into this same model without a schema change."""

    KIND_CHOICES = [
        ("published", "Published"),
        ("update", "Content Update"),
        ("correction", "Correction"),
        ("advisory", "Advisory / Release Note"),
        ("archived", "Archived"),
    ]

    article = models.ForeignKey(NewsDraft, on_delete=models.CASCADE, related_name="updates")
    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="update")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.kind}] {self.title}"
