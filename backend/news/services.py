"""Real trending-item fetch (Hacker News API + curated RSS), category
classification, AI drafting, and the digest email  the guts of the
aggregate_news pipeline (news/tasks.py).

No mocked data anywhere here: HN scores are the real live points/comments,
RSS excerpts are the feed's actual summary text, and AI drafts go through the
same core.llm client every other premium AI tool in this codebase uses.
"""
import math
import re
from datetime import datetime, timezone as dt_timezone

import feedparser
import requests
from django.conf import settings
from django.core.cache import cache

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
HN_TOP_STORIES_LIMIT = 30  # how many top-story IDs to inspect per run
# Tight per-request budget so a slow HN response can't hold a worker for long.
# (HN is only called from the aggregate_news Celery task today, so this
# doesn't directly protect gunicorn workers — but it also stops a stuck task
# from holding a Celery slot for the full 10s * 31 calls = 5+ minutes.)
REQUEST_TIMEOUT_SECONDS = (3, 5)  # (connect, read) — fail fast on both
# HN's top-stories list changes on the order of minutes; caching it for 5
# minutes eliminates ~1 outbound call per run at the cost of freshness the
# downstream trending-score gate is not sensitive to.
HN_TOPSTORIES_CACHE_KEY = "news:hn:topstories"
HN_TOPSTORIES_CACHE_TTL = 300
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CoreRipperNewsBot/1.0)"}

# Security-advisory-style sources bypass the trending-score gate entirely
# (see compute_trending_score's docstring / the spec's "security advisory
# exception")  these report real, already-vetted vulnerabilities, so
# engagement metrics like HN points don't apply the same way.
SECURITY_ADVISORY_FEEDS = {
    "The Hacker News": "https://feeds.feedburner.com/TheHackersNews",
    "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
    "Krebs on Security": "https://krebsonsecurity.com/feed/",
}

# General vendor/technology blogs  no engagement metric exists for these
# (RSS has no points/comments), so they're included by recency only (last
# 48h) rather than assigned a fabricated engagement score.
VENDOR_BLOG_FEEDS = {
    "GitHub Blog": "https://github.blog/feed/",
    "Cloudflare Blog": "https://blog.cloudflare.com/rss/",
    "Kubernetes Blog": "https://kubernetes.io/feed.xml",
    "PostgreSQL News": "https://www.postgresql.org/news.rss",
}

# Keyword table, per category, split by signal strength:
#   3 = decisive (the word essentially only appears in that domain)
#   1 = supporting (real signal, but common enough to appear elsewhere)
#
# Two rules learned the hard way here, both of which produced visibly wrong
# category chips on live cards:
#   * Generic software vocabulary must NOT sit in a specific category. "open
#     source" used to live under `linux`, so every generic OSS story ("Devtools
#     must be open source") was chipped "Linux". Anything that is equally true
#     of Windows/macOS/web software belongs in `dev`, or nowhere.
#   * Matching is word-boundary, never bare substring. As substrings, "ide"
#     matched video/guide/provider/consider, "ai" matched chain/captain, and
#     "sql" matched postgresql -- silently stealing articles into the wrong
#     category. See _compile_keywords below.
CATEGORY_KEYWORDS = {
    "security": {
        3: [
            "cve", "zero day", "0 day", "ransomware", "malware", "spyware",
            "botnet", "rootkit", "trojan", "backdoor", "phishing", "ddos",
            "data breach", "vulnerability", "vulnerabilities", "exploit",
            "exploited", "rce", "sql injection", "xss", "csrf", "infostealer",
            "privilege escalation", "supply chain attack", "threat actor",
            "patch tuesday", "cyberattack", "cybersecurity", "worm", "worms",
            "self propagating", "keylogger",
        ],
        1: [
            "security", "attacker", "attackers", "hacked", "breached",
            "compromised", "encryption", "cryptography", "authentication",
            "2fa", "mfa", "sandbox escape", "spoofing", "credential",
            "credentials", "leaked", "patched",
        ],
    },
    "networking": {
        3: [
            "dns", "bgp", "tcp", "udp", "quic", "tls handshake", "cdn",
            "load balancer", "load balancing", "subnet", "nat", "ipv4", "ipv6",
            "packet loss", "traceroute", "dhcp", "anycast", "peering",
            "cloudflare", "reverse proxy",
        ],
        1: [
            "network", "networking", "router", "routing", "firewall", "vpn",
            "latency", "bandwidth", "packet", "protocol", "throughput",
            "http 2", "http 3", "proxy",
        ],
    },
    "databases": {
        3: [
            "postgres", "postgresql", "mysql", "mariadb", "sqlite", "mongodb",
            "redis", "cassandra", "clickhouse", "duckdb", "cockroachdb",
            "query planner", "index scan", "acid", "oltp", "olap",
            "sharding", "b tree", "wal", "vacuum",
        ],
        1: [
            "database", "databases", "sql", "query", "queries", "schema",
            "migration", "transaction", "replication", "indexing",
        ],
    },
    "ai": {
        3: [
            "llm", "llms", "gpt", "openai", "anthropic", "claude", "gemini",
            "llama", "mistral", "deepseek", "qwen", "copilot", "chatgpt",
            "gemma", "grok", "falcon", "phi", "stable diffusion", "midjourney",
            "whisper", "sora", "dall e", "bert",
            "machine learning", "neural network", "transformer model",
            "diffusion model", "fine tuning", "rag", "embeddings", "inference",
            "prompt engineering", "hallucination", "agentic", "chatbot",
            "generative ai", "foundation model",
        ],
        1: [
            "ai", "model", "models", "training", "dataset", "tokens",
            "reasoning", "benchmark", "gpu cluster", "artificial intelligence",
        ],
    },
    "linux": {
        3: [
            "linux", "kernel", "ubuntu", "debian", "fedora", "arch linux",
            "systemd", "distro", "distribution release", "gnome", "kde",
            "wayland", "x11", "glibc", "btrfs", "zfs", "apt", "rpm", "dnf",
            "pacman", "busybox", "initramfs", "grub",
        ],
        1: [
            "bash", "shell", "sudo", "unix", "posix", "terminal", "daemon",
            "filesystem", "cli",
        ],
    },
    "dev": {
        3: [
            "github", "gitlab", "compiler", "typescript", "javascript",
            "python", "rust", "golang", "webassembly", "wasm", "npm",
            "package manager", "debugger", "ide", "sdk", "ci cd",
            "pull request", "refactor", "codebase", "framework", "runtime",
            "static analysis", "unit test", "devtools", "monorepo", "linter",
        ],
        1: [
            "programming", "developer", "developers", "api", "library",
            "code", "coding", "build", "release", "version", "repository",
            "documentation", "software",
            # "open source" describes a licence, not a subject: an OSS story is
            # just as likely to be about an AI model or a kernel as about a dev
            # tool. Kept as a weak signal so it can break a tie but never
            # outvote what the article is actually about. (As a strong signal
            # it pulled "Open-source engine running Gemma 26B" out of AI.)
            "open source",
        ],
    },
}

# Tie-break order when two categories score identically. Specific domains beat
# general ones, so a story that is both "a vulnerability" and "some code" reads
# as Cybersecurity, and `dev` -- the catch-all -- only wins outright.
CATEGORY_PRIORITY = ["security", "databases", "networking", "linux", "ai", "dev"]

DEFAULT_CATEGORY = "dev"

# Collapse anything that isn't a letter/digit to a single space, so hyphen,
# dot and slash spellings all normalise to the same token stream:
#   "open-source" / "open source"      -> "open source"
#   "A.I." / "AI-powered"              -> "a i" / "ai powered"
#   "zero-day" / "0-day" / "HTTP/3"    -> "zero day" / "0 day" / "http 3"
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")

# "a.i." normalises to "a i", which no keyword would match -- fold the common
# dotted spellings back to their plain form before tokenising.
_ALIASES = [
    (re.compile(r"\ba\.\s*i\.?", re.I), "ai"),
    (re.compile(r"\bm\.\s*l\.?", re.I), "ml"),
]


def _normalise(text):
    for pattern, replacement in _ALIASES:
        text = pattern.sub(replacement, text or "")
    return _NON_WORD_RE.sub(" ", (text or "").lower()).strip()


def _compile_keywords(table):
    """Pre-compile every keyword as a word-boundary regex.

    Word boundaries are the whole point: as a bare substring "ide" matches
    "video"/"guide"/"provider", "ai" matches "chain"/"captain", and "sql"
    matches "postgresql" -- each one silently mis-filing articles. \\b anchors
    every keyword to a real word so only genuine mentions count.
    """
    compiled = {}
    for category, tiers in table.items():
        compiled[category] = [
            (re.compile(r"\b" + re.escape(kw) + r"\b"), weight)
            for weight, keywords in tiers.items()
            for kw in keywords
        ]
    return compiled


_COMPILED_KEYWORDS = _compile_keywords(CATEGORY_KEYWORDS)

# The title states what a story is about; the body just mentions things in
# passing. Weighting the title stops one incidental word in a summary from
# outvoting the headline.
TITLE_WEIGHT = 3
EXCERPT_WEIGHT = 1


def classify_category(title, excerpt=""):
    """Weighted keyword classifier. Returns (category, match_count).

    match_count is the number of *distinct* keywords the winning category
    matched -- not the weighted score -- so it keeps the same meaning it has
    always had for `compute_trending_score`'s keyword_bonus term.
    """
    title_text = _normalise(title)
    excerpt_text = _normalise(excerpt)

    scores, hit_counts = {}, {}
    for category, patterns in _COMPILED_KEYWORDS.items():
        score = hits = 0
        for pattern, weight in patterns:
            in_title = bool(pattern.search(title_text))
            in_excerpt = bool(pattern.search(excerpt_text))
            if not (in_title or in_excerpt):
                continue
            hits += 1
            score += weight * (TITLE_WEIGHT if in_title else EXCERPT_WEIGHT)
        scores[category] = score
        hit_counts[category] = hits

    best_score = max(scores.values())
    if best_score == 0:
        return DEFAULT_CATEGORY, 0

    # Highest score wins; ties fall back to the explicit specificity order.
    best_category = min(
        (c for c, s in scores.items() if s == best_score),
        key=CATEGORY_PRIORITY.index,
    )
    return best_category, hit_counts[best_category]


def compute_trending_score(points, comments, hours_since_posted, category_keyword_matches):
    """Spec's formula verbatim: log-scaled engagement, decayed to 0 over 48h,
    plus a capped bonus for matching CoreRipper's own category keywords."""
    engagement = math.log1p(points) * 1.0 + math.log1p(comments) * 0.5
    recency_decay = max(0, 1 - (hours_since_posted / 48))
    keyword_bonus = min(category_keyword_matches * 10, 30)
    return (engagement * recency_decay * 10) + keyword_bonus


def _hours_since(unix_ts):
    posted = datetime.fromtimestamp(unix_ts, tz=dt_timezone.utc)
    return (datetime.now(dt_timezone.utc) - posted).total_seconds() / 3600


def _fetch_hn_items():
    """Real Hacker News top stories, scored by the formula above. HN's API
    has no article body  the excerpt is the story's own self-text (Ask/Show
    HN posts) when present, else just the title; scraping arbitrary linked
    domains for body text would be unreliable and is deliberately not done."""
    items = []
    story_ids = cache.get(HN_TOPSTORIES_CACHE_KEY)
    if story_ids is None:
        try:
            resp = requests.get(f"{HN_API_BASE}/topstories.json", timeout=REQUEST_TIMEOUT_SECONDS)
            resp.raise_for_status()
            story_ids = resp.json()[:HN_TOP_STORIES_LIMIT]
        except (requests.RequestException, ValueError):
            return items
        try:
            cache.set(HN_TOPSTORIES_CACHE_KEY, story_ids, HN_TOPSTORIES_CACHE_TTL)
        except Exception:  # noqa: BLE001  cache backend down must not break the run
            pass

    for story_id in story_ids:
        try:
            r = requests.get(f"{HN_API_BASE}/item/{story_id}.json", timeout=REQUEST_TIMEOUT_SECONDS)
            r.raise_for_status()
            item = r.json()
        except (requests.RequestException, ValueError):
            continue
        if not item or item.get("type") != "story" or not item.get("title"):
            continue

        url = item.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
        excerpt = item.get("text", "")
        category, matches = classify_category(item["title"], excerpt)
        hours = _hours_since(item.get("time", 0)) if item.get("time") else 999

        score = compute_trending_score(
            points=item.get("score", 0),
            comments=item.get("descendants", 0),
            hours_since_posted=hours,
            category_keyword_matches=matches,
        )

        items.append({
            "title": item["title"],
            "url": url,
            "source_name": "Hacker News",
            "excerpt": excerpt or item["title"],
            "category": category,
            "score": score,
            "is_security_advisory": False,
            "hours_since_posted": hours,
        })
    return items


def _entry_hours_since(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return 0  # unknown publish time  treat as fresh rather than dropping it
    posted = datetime(*parsed[:6], tzinfo=dt_timezone.utc)
    return (datetime.now(dt_timezone.utc) - posted).total_seconds() / 3600


def _fetch_feed_items(feed_map, is_security_advisory, max_age_hours=None):
    items = []
    for source_name, url in feed_map.items():
        try:
            parsed = feedparser.parse(url, request_headers=REQUEST_HEADERS)
        except Exception:  # noqa: BLE001  one dead feed must not break the run
            continue
        if getattr(parsed, "bozo", False) and not parsed.entries:
            continue

        for entry in parsed.entries[:15]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue
            excerpt = entry.get("summary", "")[:600]
            hours = _entry_hours_since(entry)
            if max_age_hours is not None and hours > max_age_hours:
                continue

            category, matches = classify_category(title, excerpt)
            if is_security_advisory:
                score = None  # bypasses the threshold gate entirely  see aggregate_news
            else:
                # No engagement metric exists for RSS  score by recency +
                # keyword relevance only, never a fabricated points/comments count.
                score = compute_trending_score(
                    points=0, comments=0, hours_since_posted=hours,
                    category_keyword_matches=matches,
                ) + settings.NEWS_FEED_TRENDING_THRESHOLD  # recency-qualified items should clear the gate

            items.append({
                "title": title,
                "url": link,
                "source_name": source_name,
                "excerpt": excerpt or title,
                "category": category if not is_security_advisory else "security",
                "score": score,
                "is_security_advisory": is_security_advisory,
                "hours_since_posted": hours,
            })
    return items


def fetch_trending_items():
    """Combines all three real sources into one candidate list. Dedup against
    already-seen source_urls and the score-gate/max-per-run cutoff both
    happen in the caller (news/tasks.py), not here  this just gathers."""
    items = []
    items.extend(_fetch_hn_items())
    items.extend(_fetch_feed_items(SECURITY_ADVISORY_FEEDS, is_security_advisory=True))
    items.extend(_fetch_feed_items(VENDOR_BLOG_FEEDS, is_security_advisory=False, max_age_hours=48))
    return items


# ------------------------------------------------------------- AI drafting

def generate_ai_draft(item):
    """Routes through the shared credits.run_ai service (user=None → always a
    free model, never Claude; news drafting must never bill anyone). Raises
    LLMNotConfigured / LLMRequestFailed (from core.llm) on failure; the caller
    (news/tasks.py) decides whether that should abort the run."""
    import json
    import re

    from credits.services import run_ai

    system = (
        "You are a technical news editor for a developer-focused tech "
        "knowledge hub. You write concise, factual, original-wording news "
        "items. You never fabricate quotes, statistics, or attributions, "
        "and you never closely mirror a source's own phrasing."
    )
    user_msg = f"""Write a short news item for a developer-focused tech knowledge hub.

Source title: {item['title']}
Source: {item['source_name']}
Source content excerpt: {item['excerpt'][:800]}
Target category: {item['category']}

Requirements:
- Write entirely in your own words  do not closely mirror the source's phrasing or structure.
- Output two parts as JSON: "summary" (1-2 sentences, for a digest email and card preview) and "body" (3-5 short paragraphs: what happened, why it matters to developers/sysadmins, and any relevant tooling angle if applicable).
- Neutral, factual tone. No speculation beyond what the source supports.
- Do not fabricate quotes, statistics, or attributions.

Respond with ONLY the JSON object, no other text."""

    result = run_ai(user=None, operation="news_draft", system=system, user_msg=user_msg)
    content = result["content"].strip()
    # Strip markdown code fences defensively  models frequently wrap JSON in
    # ```json ... ``` even when told not to.
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE).strip()

    if not content:
        raise ValueError("LLM returned an empty response — skipping draft.")

    parsed = json.loads(content)  # intentionally uncaught  caller decides how to handle a malformed draft

    def _as_text(value):
        # Models sometimes return "body" as a JSON array of paragraphs
        # instead of the single string asked for  accept both shapes.
        if isinstance(value, list):
            return "\n\n".join(str(p).strip() for p in value if str(p).strip())
        return str(value or "").strip()

    summary = _as_text(parsed.get("summary"))
    body = _as_text(parsed.get("body"))
    if not summary or not body:
        raise ValueError("AI draft response missing 'summary' or 'body'.")
    return {"summary": summary, "body": body}


# --------------------------------------------------------------- digest email

# -------------------------------------------------------------- weekly wrap-up

def generate_wrapup_summary(articles):
    """Short prose summary of everything published this cycle, for the
    weekly wrap-up email (news/tasks.py::news_weekly_wrapup). Routes through
    run_ai(user=None)  free model only, same as generate_ai_draft; never
    bills a customer wallet for an internal editorial job. Raises
    LLMNotConfigured/LLMRequestFailed on failure; the caller treats a failed
    summary as non-fatal (the clear-out still happens)."""
    from credits.services import run_ai

    system = (
        "You are a technical news editor for a developer-focused tech "
        "knowledge hub, writing a short weekly wrap-up summary email. You "
        "never fabricate facts beyond what the headlines/summaries given to "
        "you support."
    )
    items_text = "\n".join(
        f"- [{a.get_category_display()}] {a.title}: {a.ai_summary}" for a in articles
    )
    user_msg = f"""Here are the {len(articles)} news items published this week on a developer-focused tech knowledge hub:

{items_text}

Write a short (2-4 sentence) prose wrap-up summarizing the week's themes and highlights for a members' email digest. Neutral, factual tone. Do not list every item individually (they're already listed separately in the email); synthesize the throughline instead. Respond with ONLY the summary prose, no headers or preamble."""

    result = run_ai(user=None, operation="news_wrapup", system=system, user_msg=user_msg)
    return result["content"].strip()


def send_wrapup_email(user, articles, summary):
    """One subscriber's copy of the weekly wrap-up. Articles are archived,
    not deleted (see NewsDraft.archive()), so their links stay live  the
    email can safely point back to each article's own page."""
    from django.conf import settings
    from django.core.mail import send_mail

    plural = "story" if len(articles) == 1 else "stories"
    lines = [
        f"Hello{' ' + user.first_name if user.first_name else ''},",
        "",
        f"Here's your wrap-up of the {len(articles)} {plural} we covered this week.",
        "",
    ]
    if summary:
        lines += [summary, ""]

    lines.append("THIS WEEK")
    for a in articles:
        lines.append(f"  [{a.get_category_display()}] {a.title}")
        lines.append(f"  {a.ai_summary}")
        lines.append("")

    lines += [
        "These stories have now moved from the main feed into the News Archive, "
        "so the feed stays current. You can still read every one of them, and "
        "browse the full archive, at:  www.coreripper.site",
        "",
        "CoreRipper",
        "",
        "You're receiving this because product updates are switched on for your "
        "account. Turn them off any time in the Notifications tab of your settings.",
    ]

    send_mail(
        subject="Your CoreRipper weekly news wrap-up",
        message="\n".join(lines),
        from_email=settings.EMAIL_FROM_ALERTS,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_digest_email(drafts):
    from django.core.mail import send_mail

    lines = []
    for d in drafts:
        lines.append(
            f"[{d.get_category_display()}] {d.title}  (score: {d.trending_score:.0f})\n"
            f"{d.ai_summary}\n"
            f"Source: {d.source_url}\n"
            f"Review: {settings.SITE_URL}/admin/news/newsdraft/{d.id}/change/\n"
        )

    send_mail(
        subject=f"CoreRipper News: {len(drafts)} draft(s) ready for review",
        message="\n---\n".join(lines),
        from_email=settings.EMAIL_FROM_ALERTS,
        recipient_list=[settings.NEWS_FEED_REVIEWER_EMAIL],
        fail_silently=False,
    )
