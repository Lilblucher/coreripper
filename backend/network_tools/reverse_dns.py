"""
Reverse DNS (PTR) Lookup  resolves an IP address back to its hostname(s).

Uses socket.gethostbyaddr(), which asks the system's configured resolver.
Plain stdlib is sufficient here  unlike DNS Propagation Checker, there's no
need to target a specific resolver, so dnspython would add nothing.
"""
import socket


def get_reverse_dns(target):
    target = (target or "").strip()
    if not target:
        return {"status": "error", "message": "Please provide an IP address."}

    try:
        socket.inet_pton(socket.AF_INET, target)
    except OSError:
        try:
            socket.inet_pton(socket.AF_INET6, target)
        except OSError:
            return {"status": "error", "message": f"'{target}' is not a valid IPv4 or IPv6 address."}

    try:
        hostname, aliases, _ = socket.gethostbyaddr(target)
    except socket.herror:
        return {"status": "error", "message": f"No PTR record found for {target}."}
    except socket.gaierror as e:
        return {"status": "error", "message": f"Lookup failed: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}

    return {
        "status": "success",
        "result": {
            "ip": target,
            "hostname": hostname,
            "aliases": aliases,
        },
    }
