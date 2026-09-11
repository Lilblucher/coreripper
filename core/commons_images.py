"""Fetches real, freely-licensed photos from Wikimedia Commons for a search
term (e.g. a news/hardware category). Used to build the CategoryImage pool
(see core.models.CategoryImage) instead of ever faking a stock photo  this
project has no image-generation tool and no purchased stock-photo library,
so Commons (public API, no key required, every result is real and
CC-licensed) is the one honest source of real imagery available here.

Wikimedia's API etiquette requires a descriptive User-Agent identifying the
client  see https://meta.wikimedia.org/wiki/User-Agent_policy. Never strip
that header.
"""
import re

import requests

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "CoreRipper/1.0 (dev instance; category image fetcher)"


def _strip_html(raw):
    return re.sub(r"<[^>]+>", "", raw or "").strip()


def fetch_commons_images(query, limit=4, min_width=600):
    """Returns a list of dicts (possibly empty  never raises past this
    function, a network hiccup or zero-result search is an honest empty
    pool, not a fabricated image): image_url, thumb_url, credit_name,
    credit_url, license_name."""
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": 6,
        "gsrlimit": limit * 3,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 900,
        "format": "json",
    }
    try:
        res = requests.get(
            COMMONS_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=10
        )
        res.raise_for_status()
        pages = res.json().get("query", {}).get("pages", {})
    except (requests.RequestException, ValueError):
        return []

    results = []
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        thumb_url = info.get("thumburl") or info.get("url")
        if not thumb_url or info.get("thumbwidth", 0) < min_width:
            continue
        meta = info.get("extmetadata", {})
        artist = _strip_html(meta.get("Artist", {}).get("value", ""))
        results.append(
            {
                "image_url": info.get("url", thumb_url),
                "thumb_url": thumb_url,
                "credit_name": artist or "Wikimedia Commons contributor",
                "credit_url": info.get("descriptionurl", ""),
                "license_name": meta.get("LicenseShortName", {}).get("value", ""),
            }
        )
        if len(results) >= limit:
            break
    return results
