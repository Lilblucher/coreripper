"""
DMARC Checker  looks up the TXT record at _dmarc.<domain> and parses its
policy tags. Unlike DKIM, no selector is needed  the DMARC record lives at
one well-known name for every domain.
"""
from .email_txt_lookup import fetch_txt_records, parse_tag_list, DomainNotFound, LookupTimedOut

_POLICY_LABELS = {"none": "Monitor only (no enforcement)", "quarantine": "Quarantine", "reject": "Reject"}


def get_dmarc_record(target):
    target = (target or "").strip().rstrip(".")
    if not target:
        return {"status": "error", "message": "Please provide a domain."}

    query_name = f"_dmarc.{target}"

    try:
        txt_records = fetch_txt_records(query_name)
    except DomainNotFound:
        return {
            "status": "error",
            "message": f"No DMARC record found for '{target}'  this domain has not published a DMARC policy.",
        }
    except LookupTimedOut as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Lookup failed: {str(e)}"}

    dmarc_records = [r for r in txt_records if r.lower().startswith("v=dmarc1")]

    if not dmarc_records:
        return {
            "status": "error",
            "message": f"No DMARC record found for '{target}'  this domain has not published a DMARC policy.",
        }

    record = dmarc_records[0]
    tags = parse_tag_list(record)
    policy = tags.get("p", "none")

    return {
        "status": "success",
        "result": {
            "domain": target,
            "raw_record": record,
            "policy": policy,
            "policy_label": _POLICY_LABELS.get(policy, policy),
            "subdomain_policy": tags.get("sp"),
            "percentage": tags.get("pct", "100"),
            "aggregate_reports": tags.get("rua"),
            "forensic_reports": tags.get("ruf"),
            "tags": tags,
        },
    }
