"""Keyword-triggered inline tool widget selection for the article page's
"Try It Yourself" section (spec item 7: "embedded interactive widgets (DNS,
JSON, WHOIS, Regex, etc.) when relevant"). Same manually-curated spirit as
services.py's CATEGORY_KEYWORDS and related_content.py's mappings  not an
ML classifier, and deliberately conservative: an article gets a widget only
if a real keyword actually appears in it, never a default/fallback pick.

DNS Lookup / WHOIS Lookup / HTTP Headers Viewer / IP Information are
deliberately NOT in this map even though the spec names DNS/WHOIS as
examples: those four tools don't have their own page, they're anchored
sections on the shared net_tools.html multi-tool page (see core.Tool rows
with path "net_tools.html#lookupToolSection"). Embedding that whole page 
nav chrome, unrelated tool picker, and all  in an iframe would be a poor
"widget" experience, not a clean inline tool. Every other entry here embeds
a tool with a genuine standalone page.
"""
import re

# Ordered  first matching keyword wins. Word-boundary regex, case-insensitive.
KEYWORD_TOOL_SLUGS = [
    (r"\bregex(es)?\b|\bregular expressions?\b", "dev-tools-regex-tester"),
    (r"\bjson\b", "dev-tools-json-formatter"),
    (r"\bjwt\b|\bjson web tokens?\b", "dev-tools-jwt-decoder"),
    (r"\bsql\b", "dev-tools-sql-formatter"),
    (r"\bhash(ing|es)?\b|\bsha-?1\b|\bsha-?256\b|\bmd5\b", "dev-tools-hash-generator"),
    (r"\bbase64\b", "dev-tools-base64-encode-decode"),
    (r"\buuids?\b", "dev-tools-uuid-generator"),
    (r"\bsubnet(ting|s)?\b|\bcidr\b", "network-tools-cidr-calculator"),
    (r"\bssl\b|\btls certificates?\b|\bcertificate expir", "network-tools-ssl-certificate-checker"),
    (r"\bspf record", "network-tools-spf-checker"),
    (r"\bdmarc\b", "network-tools-dmarc-checker"),
    (r"\bdkim\b", "network-tools-dkim-checker"),
    (r"\bpassword strength\b|\bweak passwords?\b", "dev-tools-password-strength-checker"),
    (r"\byaml\b", "dev-tools-yaml-formatter"),
    (r"\bxml\b", "dev-tools-xml-formatter"),
    (r"\bmarkdown\b", "dev-tools-markdown-preview"),
    (r"\bunix time(stamp)?\b|\bepoch time\b", "dev-tools-timestamp-converter"),
    (r"\bport scan(ning|s|ner)?\b", "network-tools-port-scanner"),
    (r"\btraceroute\b", "network-tools-traceroute"),
]


def find_matching_tool_slug(text):
    """Returns the first matching tool slug, or None if nothing in `text`
    matches any keyword  no fallback/default widget, silence is the
    correct answer for most articles."""
    for pattern, slug in KEYWORD_TOOL_SLUGS:
        if re.search(pattern, text, re.IGNORECASE):
            return slug
    return None
