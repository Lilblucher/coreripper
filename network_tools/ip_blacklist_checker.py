"""
IP Blacklist Checker  queries public DNSBL (DNS-based blackhole list) zones
to see if an IP is flagged as a spam/abuse source. Pure stdlib: no API key,
no external HTTP calls, no rate limit beyond DNS itself.

How a DNSBL check works: for IP a.b.c.d, we query
    d.c.b.a.<blacklist-zone>
If that resolves to an A record, the IP is listed. If DNS returns NXDOMAIN
(socket.gaierror), it's clean.
"""
import socket
import concurrent.futures

# (display name, DNSBL zone)
BLACKLISTS = [
    ("Spamhaus SBL", "sbl.spamhaus.org"),
    ("Barracuda", "b.barracudacentral.org"),
    ("SORBS", "dnsbl.sorbs.org"),
    ("SpamCop", "bl.spamcop.net"),
    ("MAILSPIKE", "bl.mailspike.net"),
    ("PSBL", "psbl.surriel.com"),
]


def _check_single_zone(ip_reversed, name, zone):
    query = f"{ip_reversed}.{zone}"
    try:
        result_ip = socket.gethostbyname(query)
        return {"service": name, "status": "listed", "details": f"Listed (response: {result_ip})"}
    except socket.gaierror:
        return {"service": name, "status": "clean", "details": "Not listed"}
    except Exception as e:
        return {"service": name, "status": "error", "details": f"Check failed: {str(e)}"}


def get_blacklist_status(target):
    target = (target or "").strip()
    if not target:
        return {"status": "error", "message": "Please provide an IP address or domain."}

    # Allow typing a domain  resolve to IP first, same convenience as other tools
    ip = target
    try:
        socket.inet_aton(target)
    except socket.error:
        try:
            ip = socket.gethostbyname(target)
        except socket.gaierror:
            return {"status": "error", "message": f"Could not resolve '{target}' to an IP address."}

    octets = ip.split(".")
    if len(octets) != 4:
        return {"status": "error", "message": "IPv6 addresses aren't supported by this checker yet."}
    ip_reversed = ".".join(reversed(octets))

    socket.setdefaulttimeout(5)
    checks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(BLACKLISTS)) as executor:
        futures = [executor.submit(_check_single_zone, ip_reversed, name, zone) for name, zone in BLACKLISTS]
        for future in concurrent.futures.as_completed(futures):
            checks.append(future.result())
    socket.setdefaulttimeout(None)

    # Restore the intended display order (thread completion order is unpredictable)
    order = {name: i for i, (name, _) in enumerate(BLACKLISTS)}
    checks.sort(key=lambda c: order.get(c["service"], 999))

    listed_count = sum(1 for c in checks if c["status"] == "listed")
    overall = "listed" if listed_count > 0 else "clean"

    return {
        "status": "success",
        "result": {
            "ip": ip,
            "queried": target,
            "overall_status": overall,
            "listed_count": listed_count,
            "total_checked": len(checks),
            "checks": checks,
        },
    }