"""Curated news-category -> related-content mappings, in the same spirit as
services.py's CATEGORY_KEYWORDS: a manually-maintained dictionary, not an ML
recommender. Two separate maps because news categories don't line up 1:1
with blog Category slugs (blog has "programming"/"cybersecurity", news has
"dev"/"security"/"databases"  see news/models.py's CATEGORY_CHOICES
docstring for why news kept its own taxonomy)."""

# Ordered by relevance; the view slices to the first N. Slugs are
# core.Tool.slug values  kept as a plain list here (not a DB field) so this
# stays a simple, auditable mapping like CATEGORY_KEYWORDS, and so a
# degraded/removed tool just silently drops out (the view filters to
# status="operational") rather than needing this file edited in lockstep.
RELATED_TOOL_SLUGS = {
    "networking": [
        "network-tools-dns-lookup",
        "network-tools-subnet-calculator",
        "network-tools-traceroute",
        "network-tools-ipv6-readiness",
        "network-tools-ping-tool",
    ],
    "security": [
        "network-tools-security-grade",
        "dev-tools-password-breach-checker",
        "network-tools-spf-checker",
        "network-tools-dkim-checker",
        "network-tools-dmarc-checker",
        "network-tools-security-headers-checker",
        "network-tools-scam-detector",
        "network-tools-ip-blacklist-checker",
    ],
    "dev": [
        "dev-tools-json-formatter",
        "dev-tools-regex-tester",
        "dev-tools-jwt-decoder",
        "dev-tools-hash-generator",
        "dev-tools-base64-encode-decode",
        "dev-tools-uuid-generator",
    ],
    "ai": [
        "ai-tools-coding-helper",
        "ai-tools-grammar-clarity-checker",
        "ai-tools-pdf-reading-summarizer",
        "ai-tools-quiz-flashcard-generator",
    ],
    "databases": [
        "dev-tools-sql-formatter",
        "dev-tools-json-formatter",
    ],
    "linux": [
        "network-tools-port-scanner",
        "network-tools-traceroute",
        "dev-tools-hash-generator",
        "dev-tools-regex-tester",
    ],
}

# News category -> blog Category slug, for the "Learn More" section. Not a
# perfect taxonomy match (blog has no "dev"/"security"/"databases" category
# of its own)  "databases" maps to "programming" as the closest existing
# blog category rather than showing nothing.
RELATED_BLOG_CATEGORY_SLUGS = {
    "networking": "networking",
    "security": "cybersecurity",
    "dev": "programming",
    "ai": "ai",
    "databases": "programming",
    "linux": "linux",
}
