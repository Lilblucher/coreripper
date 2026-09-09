"""
DNSSEC Checker  reports whether a domain publishes DNSSEC signing material
(DNSKEY at the apex, DS at the parent) and whether a known DNSSEC-validating
resolver considers the zone's answers authenticated (the AD flag).

Important nuance, in the same spirit as the TLS checker's SECLEVEL fix: the
AD (Authenticated Data) flag is set by whichever resolver answers the query,
based on THAT resolver's own validation  it is not some objective property
of the zone itself. Most default/local resolvers never validate DNSSEC at
all and would report AD=False regardless of whether the zone is signed. To
make the AD flag mean something, we query Cloudflare's 1.1.1.1 directly
(a resolver known to validate) instead of the system's configured resolver.

Caveat we don't paper over: that AD flag arrives over plain UDP, which is
itself spoofable by an on-path attacker. A "Yes" here is a reasonable
signal, not cryptographic proof  a user who needs an airtight answer
should verify the signature chain locally rather than trust any single
resolver's AD bit.
"""
import dns.resolver
import dns.message
import dns.query
import dns.flags
import dns.exception

_VALIDATING_RESOLVER = "1.1.1.1"


def get_dnssec_status(target):
    target = (target or "").strip().rstrip(".")
    if not target:
        return {"status": "error", "message": "Please provide a domain."}

    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = [_VALIDATING_RESOLVER]
    resolver.timeout = 6
    resolver.lifetime = 6

    notes = []

    dnskey_count = 0
    try:
        answer = resolver.resolve(target, "DNSKEY")
        dnskey_count = len(answer)
    except dns.resolver.NXDOMAIN:
        return {"status": "error", "message": f"Domain '{target}' does not exist."}
    except dns.resolver.NoAnswer:
        pass
    except dns.exception.Timeout:
        return {"status": "error", "message": "DNS query timed out."}
    except Exception as e:
        notes.append(f"DNSKEY query failed: {e}")

    ds_present = False
    try:
        resolver.resolve(target, "DS")
        ds_present = True
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        pass
    except Exception as e:
        notes.append(f"DS query failed: {e}")

    ad_flag = False
    try:
        query = dns.message.make_query(target, "A", want_dnssec=True)
        response = dns.query.udp(query, _VALIDATING_RESOLVER, timeout=6)
        ad_flag = bool(response.flags & dns.flags.AD)
    except Exception as e:
        notes.append(f"Validation check against {_VALIDATING_RESOLVER} failed: {e}")

    signed = dnskey_count > 0

    return {
        "status": "success",
        "result": {
            "domain": target,
            "signed": signed,
            "dnskey_count": dnskey_count,
            "ds_at_parent": ds_present,
            "validated_ad_flag": ad_flag,
            "notes": notes,
        },
    }
