"""Picks one real photo from a (app, category) CategoryImage pool for a
given article  deterministic per article id, so the same article always
shows the same photo instead of flickering a different one on every reload,
while different articles in the same category still show real variety.
Returns None (not a fabricated image) when the pool is empty."""
from .models import CategoryImage

_cache = {}


def _pool(app, category):
    key = (app, category)
    if key not in _cache:
        _cache[key] = list(
            CategoryImage.objects.filter(app=app, category=category).values(
                "thumb_url", "image_url", "credit_name", "credit_url", "license_name"
            )
        )
    return _cache[key]


def get_article_image(app, category, article_id):
    pool = _pool(app, category)
    if not pool:
        return None
    return pool[article_id % len(pool)]
