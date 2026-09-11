"""
Website Screenshot Tool  captures a screenshot via thum.io's free hosted
API (no key required). No headless browser is installed on this server;
thum.io renders the page on their infrastructure and returns an image URL.

Why this instead of Playwright: rendering a real browser per-request is
heavy (300MB+ install, real CPU/RAM cost per capture) and wasn't worth it
for a VPS already running the web app + VPN workload. If that changes later,
this module is a clean drop-in swap for a Playwright-based version  same
function signature, same return contract.

Note: this module does NOT proxy/store the image bytes. It constructs the
thum.io URL, does one server-side HEAD-equivalent fetch just to confirm the
capture succeeded and measure its size, then hands the frontend the same
public image URL to load directly. This also "warms" thum.io's cache so the
browser's subsequent load is fast.
"""
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone

_WIDTH = 1920
_HEIGHT = 1080


def _normalize_url(target):
    target = target.strip()
    if not target.startswith(("http://", "https://")):
        return f"https://{target}"
    return target


def _looks_like_url(url):
    host = re.sub(r'^https?://', '', url).split('/')[0]
    return '.' in host and ' ' not in host


def capture_screenshot(target):
    target = (target or "").strip()
    if not target:
        return {"status": "error", "message": "Please provide a URL."}

    url = _normalize_url(target)
    if not _looks_like_url(url):
        return {"status": "error", "message": f"'{target}' doesn't look like a valid URL."}

    thumb_url = f"https://image.thum.io/get/width/{_WIDTH}/crop/{_HEIGHT}/{url}"

    try:
        req = urllib.request.Request(thumb_url, headers={"User-Agent": "CoreRipper-NetworkTools/1.0"})
        # thum.io renders on-demand on a cold cache  first capture of a URL
        # can take 10-20s. Cached repeat requests return almost instantly.
        with urllib.request.urlopen(req, timeout=25) as response:
            content_type = response.headers.get("Content-Type", "")
            content_length = response.headers.get("Content-Length")
            if "image" not in content_type:
                return {
                    "status": "error",
                    "message": "The screenshot service didn't return an image  the target site may be unreachable, down, or blocking automated capture.",
                }
            size_bytes = int(content_length) if content_length else None
    except urllib.error.URLError as e:
        return {"status": "error", "message": f"Could not capture screenshot: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    return {
        "status": "success",
        "result": {
            "url": url,
            "image_url": thumb_url,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "width": _WIDTH,
            "height": _HEIGHT,
            "file_size_bytes": size_bytes,
        },
    }