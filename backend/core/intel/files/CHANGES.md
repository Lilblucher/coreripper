# Image Pipeline Fix — Deployment Checklist

## What changed and why

### Problem
News articles were frequently getting no image attached, forcing manual review
of every draft. Root cause: `_score_candidate()` in `pipeline.py` multiplied
the image relevance score by Gemini's *analysis* confidence. For abstract news
topics (kernel patch, company announcement, etc.), Gemini correctly returns low
confidence (~0.4) because there is no single photographable product. So even a
perfectly good image scored: `1.5 × 0.4 = 0.60` — right at the old threshold,
randomly passing or failing. The result was unpredictable image quality forcing
you to approve everything manually.

### Fix summary
1. **`pipeline.py`** — Gemini confidence no longer multiplies the image score.
   It adds a small bonus (max 0.1) when Gemini is highly confident, but it
   cannot tank a good image. Threshold lowered from 0.60 → 0.45 to match
   actual image-relevance scores.

2. **`models_mixin.py`** — Added `intel_image_locked` BooleanField. When True,
   `refresh_article_image()` skips the article entirely. Set this flag when an
   admin manually picks a correct image so the auto-editor cannot undo it.

3. **`generate.py`** — Checks `intel_image_locked` before doing any work.

## Files to deploy

Replace these files on the server:
```
/srv/coreripper/backend/core/intel/pipeline.py
/srv/coreripper/backend/core/intel/models_mixin.py
/srv/coreripper/backend/core/intel/generate.py
```

## Migration (required — new DB column)

Run on the server for every app that uses IntelImageMixin:

```bash
cd /srv/coreripper/backend
python manage.py makemigrations news --name add_intel_image_locked
python manage.py migrate news

# If hardware or blog also use IntelImageMixin:
python manage.py makemigrations hardware --name add_intel_image_locked
python manage.py migrate hardware
python manage.py makemigrations blog --name add_intel_image_locked
python manage.py migrate blog
```

All existing rows default to `intel_image_locked=False` (unlocked), which is
the correct behaviour — nothing changes for existing articles.

## Cockpit wiring (optional but recommended)

When an admin manually changes an image in the cockpit's News tab, also set
`intel_image_locked = True` and save. This one-liner in your admin view:

```python
# In your cockpit image-update endpoint, after setting the image fields:
article.intel_image_locked = True
article.intel_image_provider = "manual"
article.save(update_fields=[..., "intel_image_locked", "intel_image_provider"])
```

To unlock (allow auto-editor to refresh again):
```python
article.intel_image_locked = False
article.save(update_fields=["intel_image_locked"])
```

## Expected result after deploy

- Most news articles will now get an image attached automatically at draft time
- The confidence threshold (0.45) means: rank-1 result from Google always
  passes (rank_score=1.0 alone > 0.45). Only articles where ALL candidates
  score poorly will still fall back to no image / category fallback.
- You only need to manually approve articles where the news itself is
  genuinely unusual — not because the image pipeline failed on normal articles.
