"""CoreRipper Intelligent content engine.

Two capabilities, one package:

1. **Intelligent image retrieval** (`gemini.py` + `image_search.py` + `pipeline.py`)
   the spec in `CoreRipper Intelligent.md`. Instead of picking a generic photo
   from a per-category pool, every article is analysed by Gemini Flash to extract
   the real subject (manufacturer / product / device type), which drives targeted
   image-search queries, multiple candidates, a confidence gate, and an honest
   placeholder fallback. Runs on the dedicated `INTEL_gen_news_gemini` key, kept
   separate from the shared premium-AI Gemini fallback so image work can never
   exhaust (or be exhausted by) the customer-facing AI budget.

2. **Automatic article editor** (`auto_editor.py`)  a scheduled pass that keeps
   already-published news / hardware / blog content fresh: it re-analyses the
   source, refreshes summary/body/SEO where the source materially changed,
   re-runs the image pipeline, updates sources, and logs a "What's New" timeline
   entry. Changes are auto-applied to published rows (a deliberate, logged
   exception to the human-moderation-on-first-publish rule  see the module
   docstring).

Honesty-first, same as the rest of the project: an unconfigured provider, a
network failure, or a low-confidence result is an honest "no image / no change",
never a fabricated image or invented fact.
"""

from .resolve import resolved_article_image  # noqa: F401  public shortcut for views
