"""Generate + persist an intelligent image onto an article row.

Thin wrapper over pipeline.resolve_article_image that any content app can call
(news aggregator, hardware ingestion, blog, the auto-editor, the backfill
command) without knowing pipeline internals. Best-effort by contract: a failure
or a low-confidence miss leaves the row untouched and returns False  it must
never break the caller's own run.
"""
from django.utils import timezone

from . import pipeline


def refresh_article_image(obj, title, body, category, force=False, save=True):
    """Resolve and store the best image for `obj` (any IntelImageMixin row).

    Skips work when:
    - intel_image_locked is True (admin manually fixed the image), unless force=True
    - The source content hash is unchanged and an image already exists, unless force=True

    Returns True if a new image was stored.
    """
    # Never overwrite a manually locked image unless explicitly forced.
    # This prevents the auto-editor from undoing an admin's manual fix.
    if not force and getattr(obj, "intel_image_locked", False):
        return False

    new_hash = pipeline.source_hash(title, body, category)
    already_has_image = bool(getattr(obj, "intel_image_url", ""))
    if not force and already_has_image and getattr(obj, "intel_source_hash", "") == new_hash:
        return False

    try:
        result = pipeline.resolve_article_image(title, body, category)
    except Exception:  # noqa: BLE001  image work must never break the caller
        result = None

    # Record that we tried (updates the change-gate) even on a miss, so a
    # scheduled pass doesn't re-attempt the same unchanged article every run.
    obj.intel_source_hash = new_hash
    if result:
        obj.apply_image_result(result)

    if save:
        update_fields = [
            "intel_source_hash", "intel_image_url", "intel_thumb_url",
            "intel_image_source", "intel_image_source_url", "intel_image_credit",
            "intel_image_credit_url", "intel_image_license", "intel_image_provider",
            "intel_image_confidence", "intel_image_query", "intel_image_updated_at",
        ]
        # Only limit update_fields when the row already exists in the DB.
        if obj.pk and not force:
            obj.save(update_fields=update_fields)
        else:
            obj.save()
    return bool(result)
