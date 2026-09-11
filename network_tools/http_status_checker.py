"""
HTTP Status Checker  makes a single HTTP request and reports the raw
status code, reason phrase, and response time. Deliberately does NOT follow
redirects (see Redirect Checker for that)  this tool tells you exactly
what the server said to your one request, nothing more.
"""
import socket
import time
import urllib.error
import urllib.request

_STATUS_CATEGORY = {
    "1": "informational",
    "2": "success",
    "3": "redirect",
    "4": "client_error",
    "5": "server_error",
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _normalize_url(url):
    url = (url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def get_http_status(target):
    url = _normalize_url(target)
    if not url:
        return {"status": "error", "message": "Please provide a URL."}

    opener = urllib.request.build_opener(_NoRedirectHandler)
    req = urllib.request.Request(url, headers={"User-Agent": "CoreRipper-NetworkTools/1.0"})

    start = time.monotonic()
    try:
        with opener.open(req, timeout=10) as response:
            elapsed_ms = round((time.monotonic() - start) * 1000)
            code = response.status
            reason = response.reason
            location = None
    except urllib.error.HTTPError as e:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        code = e.code
        reason = e.reason
        location = e.headers.get("Location")
    except urllib.error.URLError as e:
        return {"status": "error", "message": f"Could not reach {url}: {e.reason}"}
    except socket.timeout:
        return {"status": "error", "message": f"Request to {url} timed out."}
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    return {
        "status": "success",
        "result": {
            "url": url,
            "status_code": code,
            "reason": reason,
            "category": _STATUS_CATEGORY.get(str(code)[0], "unknown"),
            "response_time_ms": elapsed_ms,
            "location": location,
        },
    }
