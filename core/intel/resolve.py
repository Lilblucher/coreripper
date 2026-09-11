"""Serve-time image resolution: prefer a row's stored intelligent image, fall
back to the per-category pool exactly as before. One helper so every view
(news, hardware, blog) resolves images the same way."""
from core.category_images import get_article_image


def resolved_article_image(obj, app, category, article_id=None):
    """Return the best available image dict for an article-like row.

    1. The row's stored intelligent image (accurate, subject-specific), if any.
    2. Otherwise the deterministic per-category pool photo (legacy behaviour),
       so nothing regresses for rows the pipeline hasn't touched yet.
    3. Otherwise None  the frontend renders its icon fallback.
    """
    intel = getattr(obj, "intel_image_json", None)
    if callable(intel):
        img = obj.intel_image_json()
        if img:
            return img
    return get_article_image(app, category, article_id if article_id is not None else obj.id)
