"""
Website Uptime Checker  a one-shot "is this reachable right now" check.
This follows redirects like a browser would (unlike HTTP Status Checker,
which deliberately doesn't) and classifies the result as up/down from a
visitor's perspective, rather than reporting a raw status code.

Scope note: this is a single on-demand check, not continuous monitoring.
Real uptime monitoring needs a scheduler and historical storage  a much
bigger feature than a request/response tool like this one provides.

Unreachable hosts are reported as a successful check with up=False, not a
tool error  "the site is down" is this tool's actual job, not a failure
of it.
"""
import socket
import time
import urllib.error
import urllib.request


def _normalize_url(url):
    url = (url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def check_uptime(target):
    url = _normalize_url(target)
    if not url:
        return {"status": "error", "message": "Please provide a URL."}

    req = urllib.request.Request(url, headers={"User-Agent": "CoreRipper-NetworkTools/1.0"})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            elapsed_ms = round((time.monotonic() - start) * 1000)
            code = response.status
            final_url = response.geturl()
            up = 200 <= code < 400
            note = None
    except urllib.error.HTTPError as e:
        elapsed_ms = round((time.monotonic() - start) * 1000)
        code = e.code
        final_url = url
        up = False  # reachable, but a visitor hitting this would see an error page
        note = None
    except (urllib.error.URLError, socket.timeout) as e:
        return {
            "status": "success",
            "result": {
                "url": url,
                "up": False,
                "status_code": None,
                "final_url": None,
                "response_time_ms": None,
                "note": f"Unreachable: {getattr(e, 'reason', 'connection failed')}",
            },
        }
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    return {
        "status": "success",
        "result": {
            "url": url,
            "up": up,
            "status_code": code,
            "final_url": final_url,
            "response_time_ms": elapsed_ms,
            "note": note,
        },
    }
