"""
DKIM Checker  looks up the DKIM public key TXT record at
<selector>._domainkey.<domain>.

Unlike SPF/DMARC, a DKIM selector isn't discoverable by querying the domain
itself  the sender chooses it, and there's no well-known name to check. If
the caller doesn't supply one we guess "default", but a "not found" result
much more often means "wrong selector" than "DKIM isn't configured". We
check that the parent domain actually resolves first, purely so we can tell
those two failure modes apart instead of blaming DKIM for a typo'd domain.
"""
import dns.resolver
import dns.exception
from .email_txt_lookup import fetch_txt_records, parse_tag_list, DomainNotFound, LookupTimedOut

_COMMON_SELECTORS_HINT = "google, selector1, selector2, k1, mandrill, everlytickey1"


def get_dkim_record(target, selector="default"):
    target = (target or "").strip().rstrip(".")
    selector = (selector or "default").strip() or "default"
    if not target:
        return {"status": "error", "message": "Please provide a domain."}

    try:
        dns.resolver.resolve(target, "NS")
    except dns.resolver.NXDOMAIN:
        return {"status": "error", "message": f"Domain '{target}' does not exist."}
    except Exception:
        pass  # any other hiccup here shouldn't block the real DKIM query below

    query_name = f"{selector}._domainkey.{target}"

    try:
        txt_records = fetch_txt_records(query_name)
    except (DomainNotFound, LookupTimedOut):
        # NXDOMAIN at the selector subdomain almost always means "wrong
        # selector", not "domain doesn't exist"  we already confirmed the
        # parent domain resolves above.
        return {
            "status": "error",
            "message": f"No DKIM record found at selector '{selector}' for '{target}'. This usually means the selector is wrong, not that DKIM is unconfigured  try another (e.g. {_COMMON_SELECTORS_HINT}).",
        }
    except Exception as e:
        return {"status": "error", "message": f"Lookup failed: {str(e)}"}

    dkim_records = [r for r in txt_records if "p=" in r.lower()]

    if not dkim_records:
        return {
            "status": "error",
            "message": f"No DKIM record found at selector '{selector}' for '{target}'. This usually means the selector is wrong, not that DKIM is unconfigured  try another (e.g. {_COMMON_SELECTORS_HINT}).",
        }

    record = dkim_records[0]
    tags = parse_tag_list(record)
    pubkey = tags.get("p", "")

    return {
        "status": "success",
        "result": {
            "domain": target,
            "selector": selector,
            "raw_record": record,
            "key_type": tags.get("k", "rsa"),
            "public_key_present": bool(pubkey),
            "public_key_preview": (pubkey[:60] + "...") if len(pubkey) > 60 else pubkey,
            "tags": tags,
        },
    }
