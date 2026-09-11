"""
Open Graph Checker  fetches a page and extracts Open Graph + Twitter Card
meta tags, reporting what's present and what's missing. Uses BeautifulSoup
to parse the HTML; real-world pages are frequently malformed enough that a
regex-based approach would silently miss tags a browser renders fine.
"""
import http.client
import socket
import urllib.error
import urllib.request

from bs4 import BeautifulSoup

_RECOMMENDED_OG_TAGS = ["og:title", "og:description", "og:image", "og:url", "og:type"]
_RECOMMENDED_TWITTER_TAGS = ["twitter:card", "twitter:title", "twitter:description", "twitter:image"]
_MAX_BYTES = 2_000_000  # meta tags always live in <head>, no need to read a whole huge page


def _normalize_url(url):
    url = (url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def get_open_graph_tags(target):
    url = _normalize_url(target)
    if not url:
        return {"status": "error", "message": "Please provide a URL."}

    req = urllib.request.Request(url, headers={"User-Agent": "CoreRipper-NetworkTools/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            try:
                html = response.read(_MAX_BYTES)
            except http.client.IncompleteRead as e:
                # A capped .read(N) on a chunked response can raise this even
                # when the whole (shorter-than-N) page arrived intact 
                # e.partial is what was actually received.
                html = e.partial
    except urllib.error.HTTPError as e:
        return {"status": "error", "message": f"Server returned {e.code} {e.reason} for {url}."}
    except (urllib.error.URLError, socket.timeout) as e:
        return {"status": "error", "message": f"Could not reach {url}: {getattr(e, 'reason', e)}"}
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    soup = BeautifulSoup(html, "html.parser")

    og_tags = {}
    twitter_tags = {}
    for tag in soup.find_all("meta"):
        prop = tag.get("property") or tag.get("name")
        content = tag.get("content")
        if not prop or content is None:
            continue
        if prop.startswith("og:"):
            og_tags[prop] = content
        elif prop.startswith("twitter:"):
            twitter_tags[prop] = content

    title_tag = soup.find("title")
    page_title = title_tag.get_text(strip=True) if title_tag else None

    og_missing = [t for t in _RECOMMENDED_OG_TAGS if t not in og_tags]
    twitter_missing = [t for t in _RECOMMENDED_TWITTER_TAGS if t not in twitter_tags]

    return {
        "status": "success",
        "result": {
            "url": url,
            "page_title": page_title,
            "og_tags": og_tags,
            "og_missing": og_missing,
            "twitter_tags": twitter_tags,
            "twitter_missing": twitter_missing,
            "has_minimum_og": len(og_missing) == 0,
        },
    }
