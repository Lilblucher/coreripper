"""
MX Lookup  queries the MX record set for a domain, sorted by preference
(lower number = higher priority, per RFC 5321).
"""
import dns.resolver
import dns.exception


def get_mx_records(target):
    target = (target or "").strip().rstrip(".")
    if not target:
        return {"status": "error", "message": "Please provide a domain."}

    try:
        answer = dns.resolver.resolve(target, "MX")
    except dns.resolver.NXDOMAIN:
        return {"status": "error", "message": f"Domain '{target}' does not exist."}
    except dns.resolver.NoAnswer:
        return {
            "status": "error",
            "message": f"No MX records found for '{target}'. This domain may not accept email, or mail may be routed some other way.",
        }
    except dns.exception.Timeout:
        return {"status": "error", "message": "DNS query timed out."}
    except Exception as e:
        return {"status": "error", "message": f"Lookup failed: {str(e)}"}

    records = sorted(
        (
            {"priority": rdata.preference, "server": str(rdata.exchange).rstrip(".")}
            for rdata in answer
        ),
        key=lambda r: r["priority"],
    )

    return {
        "status": "success",
        "result": {
            "domain": target,
            "record_count": len(records),
            "records": records,
        },
    }
