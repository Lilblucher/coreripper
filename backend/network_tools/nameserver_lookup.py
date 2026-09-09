"""
Nameserver Lookup  queries the NS record set for a domain and resolves each
nameserver's own IP address for convenience.
"""
import socket
import dns.resolver
import dns.exception


def get_nameservers(target):
    target = (target or "").strip().rstrip(".")
    if not target:
        return {"status": "error", "message": "Please provide a domain."}

    try:
        answer = dns.resolver.resolve(target, "NS")
    except dns.resolver.NXDOMAIN:
        return {"status": "error", "message": f"Domain '{target}' does not exist."}
    except dns.resolver.NoAnswer:
        return {"status": "error", "message": f"No NS records found for '{target}'."}
    except dns.exception.Timeout:
        return {"status": "error", "message": "DNS query timed out."}
    except Exception as e:
        return {"status": "error", "message": f"Lookup failed: {str(e)}"}

    nameservers = []
    for rdata in answer:
        host = str(rdata.target).rstrip(".")
        try:
            ip = socket.gethostbyname(host)
        except socket.gaierror:
            ip = None
        nameservers.append({"hostname": host, "ip": ip})

    nameservers.sort(key=lambda n: n["hostname"])

    return {
        "status": "success",
        "result": {
            "domain": target,
            "nameserver_count": len(nameservers),
            "nameservers": nameservers,
        },
    }
