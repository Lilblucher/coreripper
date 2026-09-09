"""
Sitemap Validator  fetches an XML sitemap and validates its structure
against the sitemaps.org protocol: correct namespace, required <loc> tags,
syntactically valid URLs, and the 50,000-URL / 50MB size limits.
"""
import http.client
import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

MAX_URLS = 50_000
MAX_BYTES = 50 * 1024 * 1024
_SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _normalize_url(url):
    url = (url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _find_first(element, tag):
    # NB: an ElementTree Element with no sub-children is falsy even when
    # found, so `find(a) or find(b)` silently discards a real match. Must
    # check against None explicitly instead.
    found = element.find(f"{{{_SITEMAP_NS}}}{tag}")
    if found is None:
        found = element.find(tag)
    return found


def validate_sitemap(target):
    url = _normalize_url(target)
    if not url:
        return {"status": "error", "message": "Please provide a sitemap URL."}

    req = urllib.request.Request(url, headers={"User-Agent": "CoreRipper-NetworkTools/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            try:
                raw = response.read(MAX_BYTES + 1)
            except http.client.IncompleteRead as e:
                raw = e.partial
    except urllib.error.HTTPError as e:
        return {"status": "error", "message": f"Server returned {e.code} {e.reason} fetching the sitemap."}
    except (urllib.error.URLError, socket.timeout) as e:
        return {"status": "error", "message": f"Could not reach {url}: {getattr(e, 'reason', e)}"}
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    size_bytes = len(raw)
    if size_bytes > MAX_BYTES:
        return {
            "status": "success",
            "result": {
                "url": url,
                "sitemap_type": None,
                "entry_count": None,
                "url_count": None,
                "size_bytes": size_bytes,
                "valid": False,
                "issues": [
                    f"File exceeds the 50MB sitemap protocol limit  stopped downloading at that point, "
                    f"so its internal structure wasn't checked."
                ],
                "invalid_urls_sample": [],
            },
        }

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        return {"status": "error", "message": f"Not valid XML: {e}"}

    tag = root.tag
    is_sitemap_index = tag.endswith("sitemapindex")
    is_urlset = tag.endswith("urlset")

    issues = []
    if not tag.startswith(f"{{{_SITEMAP_NS}}}"):
        issues.append(f"Root element doesn't use the standard sitemap namespace ({_SITEMAP_NS}).")

    if not (is_sitemap_index or is_urlset):
        return {
            "status": "error",
            "message": f"Root element is '{tag.split('}')[-1]}', expected 'urlset' or 'sitemapindex'.",
        }

    child_tag = "sitemap" if is_sitemap_index else "url"
    entries = root.findall(f"{{{_SITEMAP_NS}}}{child_tag}")
    if not entries:
        entries = root.findall(child_tag)

    url_count = 0
    invalid_urls = []
    missing_loc = 0

    for entry in entries:
        loc_el = _find_first(entry, "loc")
        if loc_el is None or not (loc_el.text or "").strip():
            missing_loc += 1
            continue
        url_count += 1
        loc = loc_el.text.strip()
        parsed = urlparse(loc)
        if not (parsed.scheme and parsed.netloc):
            invalid_urls.append(loc)

    if missing_loc:
        issues.append(f"{missing_loc} entr{'y is' if missing_loc == 1 else 'ies are'} missing a required <loc> tag.")
    if invalid_urls:
        issues.append(f"{len(invalid_urls)} <loc> value(s) are not well-formed URLs.")
    if url_count > MAX_URLS:
        issues.append(f"Contains {url_count} URLs, exceeding the {MAX_URLS:,} sitemap protocol limit.")

    return {
        "status": "success",
        "result": {
            "url": url,
            "sitemap_type": "sitemap_index" if is_sitemap_index else "urlset",
            "entry_count": len(entries),
            "url_count": url_count,
            "size_bytes": size_bytes,
            "valid": len(issues) == 0,
            "issues": issues,
            "invalid_urls_sample": invalid_urls[:10],
        },
    }
