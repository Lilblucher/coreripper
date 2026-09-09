"""
Reverse IP Lookup  find other domains hosted on the same IP address.
Uses HackerTarget's free reverseiplookup API (no key, rate-limited).
Docs: https://hackertarget.com/reverse-ip-lookup/
"""
import socket
import urllib.request
import urllib.parse
import urllib.error


def get_reverse_ip(target):
    """
    Accepts an IP address OR a domain (resolved to IP first, same convenience
    as the other tools). Returns the standard {"status", ...} contract.
    """
    target = (target or "").strip()
    if not target:
        return {"status": "error", "message": "Please provide an IP address or domain."}

    # Allow typing a domain  resolve to IP first, mirrors ip_info.py's behavior
    ip = target
    try:
        socket.inet_aton(target)
    except socket.error:
        try:
            ip = socket.gethostbyname(target)
        except socket.gaierror:
            return {"status": "error", "message": f"Could not resolve '{target}' to an IP address."}

    url = f"https://api.hackertarget.com/reverseiplookup/?q={urllib.parse.quote(ip)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CoreRipper-NetworkTools/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8", errors="replace").strip()
    except urllib.error.URLError as e:
        return {"status": "error", "message": f"Could not reach HackerTarget API: {e.reason}"}
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error contacting HackerTarget: {str(e)}"}

    # HackerTarget signals problems via plain-text body, not HTTP status codes
    lowered = raw.lower()
    if "api count exceeded" in lowered:
        return {"status": "error", "message": "HackerTarget free API rate limit reached (50/day per IP). Try again later."}
    if "error" in lowered or "invalid" in lowered or not raw:
        return {"status": "error", "message": raw or f"No domains found hosted on {ip}."}

    domains = [line.strip() for line in raw.splitlines() if line.strip()]
    if not domains:
        return {"status": "error", "message": f"No domains found hosted on {ip}."}

    return {
        "status": "success",
        "result": {
            "ip": ip,
            "queried": target,
            "domain_count": len(domains),
            "domains": domains,
        },
    }