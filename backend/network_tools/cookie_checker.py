"""
Cookie Flag Checker  probes a domain's homepage response for Set-Cookie
headers missing the Secure/HttpOnly flags. Small helper used internally by
the Security Grade composite scan (network_tools/scoring.py); not exposed
as its own dispatcher tool_key.

Pure stdlib (urllib)  no external dependencies.
"""
import urllib.request
import urllib.error


def _normalize_url(target):
    target = target.strip()
    if not target.startswith(("http://", "https://")):
        return f"https://{target}"
    return target


def check_cookie_flags(target):
    target = (target or "").strip()
    if not target:
        return {"status": "error", "message": "Please provide a domain or URL."}

    url = _normalize_url(target)
    req = urllib.request.Request(url, headers={"User-Agent": "CoreRipper-NetworkTools/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            # A domain can set multiple cookies across several Set-Cookie
            # headers  get_all() is required since dict(response.headers)
            # would silently keep only the last one.
            raw_cookies = response.headers.get_all("Set-Cookie") or []
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        raw_cookies = getattr(e, "headers", None)
        raw_cookies = raw_cookies.get_all("Set-Cookie") if raw_cookies else []
        if not raw_cookies and isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError):
            return {"status": "error", "message": f"Could not reach {url}."}

    if not raw_cookies:
        return {
            "status": "success",
            "result": {
                "url": url,
                "cookies_found": 0,
                "missing_secure_flag": False,
                "missing_httponly_flag": False,
                "cookies": [],
            },
        }

    cookies = []
    missing_secure = False
    missing_httponly = False
    for raw in raw_cookies:
        parts = [p.strip() for p in raw.split(";")]
        name = parts[0].split("=", 1)[0] if parts else "?"
        flags_lower = [p.lower() for p in parts[1:]]
        has_secure = "secure" in flags_lower
        has_httponly = "httponly" in flags_lower
        if not has_secure:
            missing_secure = True
        if not has_httponly:
            missing_httponly = True
        cookies.append({"name": name, "secure": has_secure, "httponly": has_httponly})

    return {
        "status": "success",
        "result": {
            "url": url,
            "cookies_found": len(cookies),
            "missing_secure_flag": missing_secure,
            "missing_httponly_flag": missing_httponly,
            "cookies": cookies,
        },
    }
