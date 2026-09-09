"""Reusable intelligent-image storage, shared by every article model.

An abstract base, not a shared table: each concrete model (NewsDraft,
HardwareArticle, blog Post) gets its own columns via its own app's migration, so
one app's migrations never touch another's data  the same per-app-shape rule the
content-moderation models already follow. The behaviour lives here once instead
of being copy-pasted three times.

`intel_source_hash` is the change-gate: the auto-editor only regenerates when the
hash of the tracked source fields changes, so a scheduled pass over unchanged
content is a cheap no-op (mirrors the hardware AI-profile regeneration rule).

`intel_image_locked` is the override gate: when an admin manually selects a
correct image via the cockpit, this flag is set True and the auto-editor will
never overwrite that choice, even if the source content changes.
"""
from django.db import models


class IntelImageMixin(models.Model):
    # The resolved image + provenance. Blank = never resolved (fall back to the
    # per-category pool at serve time, exactly as before this feature existed).
    intel_image_url = models.URLField(max_length=1000, blank=True)
    intel_thumb_url = models.URLField(max_length=1000, blank=True)
    intel_image_source = models.CharField(max_length=150, blank=True, help_text="e.g. 'Wikimedia Commons' or a domain")
    intel_image_source_url = models.URLField(max_length=1000, blank=True)
    intel_image_credit = models.CharField(max_length=200, blank=True)
    intel_image_credit_url = models.URLField(max_length=1000, blank=True)
    intel_image_license = models.CharField(max_length=120, blank=True)
    intel_image_provider = models.CharField(max_length=20, blank=True, help_text="google | commons | manual")
    intel_image_confidence = models.FloatField(null=True, blank=True)
    intel_image_query = models.CharField(max_length=300, blank=True)

    # Auto-editor bookkeeping.
    intel_source_hash = models.CharField(max_length=64, blank=True, help_text="Change-gate: unchanged => scheduled refresh is a no-op")
    intel_image_updated_at = models.DateTimeField(null=True, blank=True)
    intel_last_edited_at = models.DateTimeField(null=True, blank=True, help_text="When the auto-editor last ran a real refresh")

    # Manual-override gate. Set True by the cockpit when an admin picks a
    # correct image by hand. The auto-editor and aggregate_news pipeline both
    # check this before overwriting, so a manually fixed image is permanent
    # until an admin explicitly unlocks it.
    intel_image_locked = models.BooleanField(
        default=False,
        help_text="When True, the auto-editor will not replace this image. "
                  "Set automatically when an admin manually selects an image via the cockpit.",
    )

    class Meta:
        abstract = True

    def apply_image_result(self, result, lock=False):
        """Copy a pipeline ImageResult dict onto this row (does not save).

        Pass lock=True when the image is being set by a human admin so the
        auto-editor cannot overwrite it later.
        """
        from django.utils import timezone

        self.intel_image_url = result["image_url"]
        self.intel_thumb_url = result.get("thumb_url") or result["image_url"]
        self.intel_image_source = result.get("source_name", "")
        self.intel_image_source_url = result.get("source_url", "")
        self.intel_image_credit = result.get("credit_name", "")
        self.intel_image_credit_url = result.get("credit_url", "")
        self.intel_image_license = result.get("license_name", "")
        self.intel_image_provider = result.get("provider", "")
        self.intel_image_confidence = result.get("confidence")
        self.intel_image_query = result.get("search_query", "")[:300]
        self.intel_image_updated_at = timezone.now()
        if lock:
            self.intel_image_locked = True

    def intel_image_json(self):
        """The image dict the frontend expects (same shape as
        core.category_images.get_article_image), or None if unresolved."""
        if not self.intel_image_url:
            return None
        return {
            "image_url": self.intel_image_url,
            "thumb_url": self.intel_thumb_url or self.intel_image_url,
            # Real photo credit only -- no fallback to intel_image_source. A
            # manually-uploaded image has no external photographer to credit
            # (source_name is just "Manual upload", an internal admin label,
            # not attribution), so credit_name stays empty and the frontend
            # skips the "Photo: ..." badge entirely rather than showing that
            # label to visitors.
            "credit_name": self.intel_image_credit,
            "credit_url": self.intel_image_credit_url or self.intel_image_source_url,
            "license_name": self.intel_image_license,
            "source_name": self.intel_image_source,
            "provider": self.intel_image_provider,
            "confidence": self.intel_image_confidence,
            "locked": self.intel_image_locked,
        }
