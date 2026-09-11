"""
CORS Checker  probes a URL for Cross-Origin Resource Sharing configuration.

Sends an OPTIONS preflight request (mimicking what a browser sends before a
cross-origin fetch/XHR with custom headers) and reads back the
Access-Control-* response headers. Falls back to a plain GET-with-Origin
request if the server doesn't respond to OPTIONS with any CORS headers,
since some servers only reflect Access-Control-Allow-Origin on the actual
request rather than the preflight.

Pure stdlib (urllib)  no external dependencies.
"""
import urllib.request
import urllib.error

# A believable but clearly-inert probe origin
_PROBE_ORIGIN = "https://corslom-probe.example.com"

_CORS_HEADER_NAMES = [
    "Access-Control-Allow-Origin",
    "Access-Control-Allow-Methods",
    "Access-Control-Allow-Headers",
    "Access-Control-Allow-Credentials",
    "Access-Control-Max-Age",
    "Vary",
]


def _normalize_url(target):
    target = target.strip()
    if not target.startswith(("http://", "https://")):
        return f"https://{target}"
    return target


def _fetch_headers(url, method):
    """Returns a dict of response headers, or None on a connection-level failure."""
    headers = {"Origin": _PROBE_ORIGIN, "User-Agent": "CoreRipper-NetworkTools/1.0"}
    if method == "OPTIONS":
        headers["Access-Control-Request-Method"] = "GET"
        headers["Access-Control-Request-Headers"] = "Content-Type, Authorization"

    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return dict(response.headers)
    except urllib.error.HTTPError as e:
        # Plenty of servers respond to OPTIONS with 4xx/405 but still set CORS
        # headers on that same response  don't treat this as a failure.
        return dict(e.headers) if e.headers else {}
    except urllib.error.URLError:
        return None


def check_cors(target):
    target = (target or "").strip()
    if not target:
        return {"status": "error", "message": "Please provide a domain or URL."}

    url = _normalize_url(target)

    options_headers = _fetch_headers(url, "OPTIONS")
    if options_headers is None:
        return {"status": "error", "message": f"Could not reach {url}."}

    # If the preflight didn't reveal anything, some servers only set CORS
    # headers on the real request  try a plain GET as a fallback.
    get_headers = {}
    if not options_headers.get("Access-Control-Allow-Origin"):
        fetched = _fetch_headers(url, "GET")
        if fetched:
            get_headers = fetched

    def pick(name):
        return options_headers.get(name) or get_headers.get(name)

    allow_origin = pick("Access-Control-Allow-Origin")

    return {
        "status": "success",
        "result": {
            "url": url,
            "cors_enabled": allow_origin is not None,
            "allow_origin": allow_origin,
            "allow_methods": pick("Access-Control-Allow-Methods"),
            "allow_headers": pick("Access-Control-Allow-Headers"),
            "allow_credentials": pick("Access-Control-Allow-Credentials"),
            "max_age": pick("Access-Control-Max-Age"),
            "vary": pick("Vary"),
        },
    }