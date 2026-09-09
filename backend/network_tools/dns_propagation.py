"""
DNS Propagation Checker  queries the same A record for a domain against
several well-known public DNS resolvers and compares the answers. Useful for
confirming whether a recent DNS change has propagated everywhere, or is
still cached/stale at some resolvers.

Needs dnspython (already installed) since stdlib's socket module only ever
asks the system's configured resolver  there's no way to target a specific
resolver with socket.gethostbyname().
"""
import concurrent.futures
import dns.resolver
import dns.exception

# (display name, resolver IP)
RESOLVERS = [
    ("Google", "8.8.8.8"),
    ("Cloudflare", "1.1.1.1"),
    ("Quad9", "9.9.9.9"),
    ("OpenDNS", "208.67.222.222"),
    ("Verisign", "64.6.64.6"),
    ("Comodo Secure DNS", "8.26.56.26"),
]


def _query_single_resolver(domain, name, ip):
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = [ip]
    resolver.timeout = 5
    resolver.lifetime = 5
    try:
        answer = resolver.resolve(domain, "A")
        records = sorted(r.address for r in answer)
        return {"resolver": name, "resolver_ip": ip, "status": "ok", "records": records}
    except dns.resolver.NXDOMAIN:
        return {"resolver": name, "resolver_ip": ip, "status": "nxdomain", "records": []}
    except dns.resolver.NoAnswer:
        return {"resolver": name, "resolver_ip": ip, "status": "no_answer", "records": []}
    except dns.exception.Timeout:
        return {"resolver": name, "resolver_ip": ip, "status": "timeout", "records": []}
    except Exception as e:
        return {"resolver": name, "resolver_ip": ip, "status": "error", "records": [], "detail": str(e)}


def get_dns_propagation(target):
    target = (target or "").strip().rstrip(".")
    if not target:
        return {"status": "error", "message": "Please provide a domain."}

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(RESOLVERS)) as executor:
        futures = [executor.submit(_query_single_resolver, target, name, ip) for name, ip in RESOLVERS]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    # Restore intended display order (thread completion order is unpredictable)
    order = {name: i for i, (name, _) in enumerate(RESOLVERS)}
    results.sort(key=lambda r: order.get(r["resolver"], 999))

    if all(r["status"] in ("error", "timeout") for r in results):
        return {
            "status": "error",
            "message": f"Could not reach any resolver to check '{target}'. Check the domain and try again.",
        }

    # Do all resolvers that returned a real answer agree with each other?
    answer_sets = [tuple(r["records"]) for r in results if r["status"] == "ok" and r["records"]]
    unique_answers = set(answer_sets)
    fully_propagated = len(answer_sets) > 0 and len(unique_answers) == 1

    return {
        "status": "success",
        "result": {
            "domain": target,
            "fully_propagated": fully_propagated,
            "resolvers_checked": len(results),
            "resolvers_answered": len(answer_sets),
            "checks": results,
        },
    }
