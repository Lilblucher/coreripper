import urllib.request

# Each header's scoring weight (100 total) and whether it's deprecated
# (deprecated headers are checked but weighted low since browsers largely
# ignore them now, e.g. X-XSS-Protection).
SECURITY_HEADERS = {
    "Strict-Transport-Security": {"weight": 20, "deprecated": False},
    "Content-Security-Policy": {"weight": 25, "deprecated": False},
    "X-Frame-Options": {"weight": 15, "deprecated": False},
    "X-Content-Type-Options": {"weight": 10, "deprecated": False},
    "Referrer-Policy": {"weight": 10, "deprecated": False},
    "Permissions-Policy": {"weight": 15, "deprecated": False},
    "X-XSS-Protection": {"weight": 5, "deprecated": True},
}


def _grade_for(score):
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def get_security_headers(domain):
    url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CoreRipper-SecurityHeadersChecker/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            headers = dict(response.getheaders())
    except Exception as e:
        return {"status": "error", "message": f"Could not fetch headers for '{domain}': {str(e)}"}

    # HTTP header names are case-insensitive, so normalize before lookup
    lower_headers = {k.lower(): v for k, v in headers.items()}

    rows = []
    earned = 0
    total_weight = sum(h["weight"] for h in SECURITY_HEADERS.values())

    for name, meta in SECURITY_HEADERS.items():
        value = lower_headers.get(name.lower())
        present = value is not None
        if present:
            earned += meta["weight"]
        rows.append({
            "header": name,
            "value": value if present else ("Not set (deprecated header)" if meta["deprecated"] else "Not set"),
            "present": present,
        })

    score = round((earned / total_weight) * 100) if total_weight else 0

    return {
        "status": "success",
        "result": {
            "domain": domain,
            "score": score,
            "grade": _grade_for(score),
            "headers": rows,
        }
    }