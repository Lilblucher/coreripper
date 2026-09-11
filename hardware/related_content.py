"""Knowledge-integration mappings for hardware articles  same
hand-curated, no-forced-matches philosophy as news/related_content.py.

related_hardware (other published articles in the same category) is
populated for real right now. The rest are deliberately left empty rather
than forced:
- HARDWARE_TOOL_SLUGS (existing core.Tool links): no CoreRipper tool today
  overlaps with hardware content the way e.g. a DNS checker overlaps with a
  networking news article.
- HARDWARE_TO_NEWS_CATEGORY / HARDWARE_TO_BLOG_CATEGORY: news' categories
  (networking/security/dev/ai/databases/linux) and blog's categories
  (programming/linux/networking/ai/cybersecurity) don't genuinely overlap
  with CPU/GPU/laptop review content the way news' "security"->"cybersecurity"
  did. Forcing a weak match (e.g. "cpus"->"programming") would repeat the
  mistake this project explicitly avoids elsewhere: don't curate a fake
  relationship just to fill a field. Left unmapped until real overlapping
  content exists (e.g. a "PC Building" piece that's genuinely also a Linux
  story).
"""

# See module docstring  intentionally empty today.
HARDWARE_TOOL_SLUGS = {}
HARDWARE_TO_NEWS_CATEGORY = {}
HARDWARE_TO_BLOG_CATEGORY = {}
