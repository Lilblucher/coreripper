from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from core.intel.models_mixin import IntelImageMixin


class Category(models.Model):
    name = models.CharField(max_length=64, unique=True)
    slug = models.SlugField(max_length=64, unique=True)
    description = models.CharField(max_length=200, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Post(IntelImageMixin, models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="posts")
    excerpt = models.CharField(max_length=300)
    content = models.TextField(help_text="Markdown")
    cover_image_url = models.URLField(
        max_length=500, blank=True, help_text="Optional. Falls back to a category icon if blank."
    )
    meta_description = models.CharField(max_length=160, blank=True)
    author_name = models.CharField(max_length=80, default="CoreRipper Team")
    author_initials = models.CharField(max_length=4, default="CL")
    reading_time_minutes = models.PositiveSmallIntegerField(default=0, help_text="0 = auto-calculate from content")
    is_published = models.BooleanField(default=False)
    # Auto-editor opt-in. Hand-written posts (all existing seed content) default
    # to False so the scheduled refresh only ever touches image + SEO + a
    # "what's new" note on them, never rewrites their body. Set True on an
    # AI-managed post to let the auto-editor refresh its body text too.
    auto_managed = models.BooleanField(default=False, help_text="If set, the auto-editor may refresh this post's body text, not just its image/SEO.")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        if self.is_published and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def computed_reading_time(self):
        if self.reading_time_minutes:
            return self.reading_time_minutes
        from core.reading_time import estimate_reading_minutes

        return estimate_reading_minutes(self.content)
