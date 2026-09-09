"""
IPv6 Readiness Tester  checks whether a domain has an AAAA record, whether
HTTPS is actually reachable over that IPv6 address, and whether the zone is
DNSSEC-signed (reuses dnssec_checker.py directly, not via the dispatcher, to
avoid a circular import with network_tools.views). Aggregates to a simple
pass/warn/fail rather than an A-F letter grade  a 3-state reads clearer for
a single narrow check.
"""
import socket
import ssl

import dns.resolver
import dns.exception

from .dnssec_checker import get_dnssec_status


def check_ipv6_readiness(target):
    target = (target or "").strip().rstrip(".")
    if not target:
        return {"status": "error", "message": "Please provide a domain."}

    resolver = dns.resolver.Resolver()
    resolver.timeout = 6
    resolver.lifetime = 6

    aaaa_addresses = []
    try:
        answer = resolver.resolve(target, "AAAA")
        aaaa_addresses = [str(r) for r in answer]
    except dns.resolver.NXDOMAIN:
        return {"status": "error", "message": f"Domain '{target}' does not exist."}
    except dns.resolver.NoAnswer:
        pass
    except dns.exception.Timeout:
        return {"status": "error", "message": "DNS query timed out."}
    except Exception:
        pass

    has_aaaa = bool(aaaa_addresses)

    https_reachable = False
    https_error = None
    if has_aaaa:
        try:
            addr = aaaa_addresses[0]
            ctx = ssl.create_default_context()
            with socket.create_connection((addr, 443), timeout=6) as sock:
                with ctx.wrap_socket(sock, server_hostname=target):
                    https_reachable = True
        except Exception as e:
            https_error = str(e)

    dnssec_signed = False
    dnssec_result = get_dnssec_status(target)
    if dnssec_result.get("status") == "success":
        dnssec_signed = bool(dnssec_result["result"].get("signed"))

    if not has_aaaa:
        readiness = "fail"
    elif not https_reachable:
        readiness = "warn"
    else:
        readiness = "pass"

    return {
        "status": "success",
        "result": {
            "domain": target,
            "has_aaaa": has_aaaa,
            "aaaa_addresses": aaaa_addresses,
            "https_reachable_over_ipv6": https_reachable,
            "https_error": https_error,
            "dnssec_signed": dnssec_signed,
            "readiness": readiness,
        },
    }
