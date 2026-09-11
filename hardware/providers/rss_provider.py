"""Generic RSS ingestion provider  the first real implementation of
HardwareSourceProvider, reused by every publication wired into
hardware/providers/sources.py. Same feedparser pattern as
news/services.py's _fetch_feed_items, adapted to hardware's fetch() dict
shape (see base.py's docstring). Each publication's specifics (feed URL,
which categories it plausibly covers, keywords to pick among them) are
metadata passed to __init__, not new logic  one implementation per the
provider architecture's design, not five near-duplicate classes.
"""
import html
import re
from datetime import datetime, timezone as dt_timezone

import feedparser

from .base import HardwareSourceProvider

REQUEST_TIMEOUT_SECONDS = 10
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CoreRipperHardwareBot/1.0)"}

_TAG_RE = re.compile(r"<[^>]+>")

# Some feeds (PC Gamer's is the confirmed offender) put a one-line stylistic
# subhead in <summary> instead of real lead-paragraph text ("Opportunity NOX
# twice."), which otherwise sails straight through to a "pending" draft with
# no real body for a human to review. Drop those at ingestion rather than
# publishing/queuing a near-empty article - this is a source-quality filter,
# not a truncation of anything real.
MIN_EXCERPT_CHARS = 50


def _entry_hours_since(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return 0  # unknown publish time  treat as fresh rather than dropping it
    posted = datetime(*parsed[:6], tzinfo=dt_timezone.utc)
    return (datetime.now(dt_timezone.utc) - posted).total_seconds() / 3600


class RSSFeedProvider(HardwareSourceProvider):
    """One RSS/Atom feed.

    - `category_keywords`: {category_key: [keywords...]}  the categories
      this publication can plausibly cover, each with keyword hints. The
      entry is classified into whichever matches the most keywords; an
      entry matching none of them is dropped rather than force-assigned to
      a wrong category (mirrors news/services.py's classify_category, but
      scoped per-publication instead of one dict for all categories).
    - `single_category`: for a publication that covers exactly one category
      (e.g. VideoCardz is GPU-only)  skips classification entirely.
    """

    def __init__(
        self, name, feed_url, category_keywords=None, single_category=None,
        max_entries=15, max_age_hours=None,
    ):
        self.name = name
        self.feed_url = feed_url
        self.category_keywords = category_keywords or {}
        self.single_category = single_category
        self.max_entries = max_entries
        self.max_age_hours = max_age_hours

    def _classify(self, title, excerpt):
        if self.single_category:
            return self.single_category
        text = f" {title.lower()} {excerpt.lower()} "
        best_category, best_count = None, 0
        for category, keywords in self.category_keywords.items():
            count = sum(1 for kw in keywords if kw in text)
            if count > best_count:
                best_category, best_count = category, count
        return best_category  # None if nothing matched  caller drops the item

    def fetch(self):
        items = []
        try:
            parsed = feedparser.parse(self.feed_url, request_headers=REQUEST_HEADERS)
        except Exception:  # noqa: BLE001  a malformed/unreachable feed must not break the run
            return items
        if getattr(parsed, "bozo", False) and not parsed.entries:
            return items

        for entry in parsed.entries[: self.max_entries]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue
            excerpt = html.unescape(_TAG_RE.sub("", entry.get("summary", "")))[:600].strip()
            hours = _entry_hours_since(entry)
            if self.max_age_hours is not None and hours > self.max_age_hours:
                continue

            category = self._classify(title, excerpt)
            if not category:
                continue  # doesn't clearly belong to any category this publication covers

            final_excerpt = excerpt or title
            if len(final_excerpt) < MIN_EXCERPT_CHARS:
                continue  # too thin to be a real summary, not just a truncated one

            items.append(
                {
                    "title": title,
                    "url": link,
                    "source_name": self.name,
                    "category": category,
                    "excerpt": final_excerpt,
                }
            )
        return items
