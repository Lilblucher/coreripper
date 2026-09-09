"""
SPF Checker  finds the TXT record starting with "v=spf1" and breaks its
mechanisms down individually. SPF is published as a TXT record (the
dedicated SPF RR type was deprecated by RFC 7208), so this is a TXT lookup
plus a prefix match, not a distinct DNS record type.
"""
from .email_txt_lookup import fetch_txt_records, DomainNotFound, LookupTimedOut

_QUALIFIERS = {"+": "pass", "-": "fail", "~": "softfail", "?": "neutral"}


def _parse_mechanism(token):
    qualifier = "pass"  # '+' is the implicit default qualifier per RFC 7208
    if token and token[0] in _QUALIFIERS:
        qualifier = _QUALIFIERS[token[0]]
        token = token[1:]
    return {"mechanism": token, "qualifier": qualifier}


def get_spf_record(target):
    target = (target or "").strip().rstrip(".")
    if not target:
        return {"status": "error", "message": "Please provide a domain."}

    try:
        txt_records = fetch_txt_records(target)
    except DomainNotFound:
        return {"status": "error", "message": f"Domain '{target}' does not exist."}
    except LookupTimedOut as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Lookup failed: {str(e)}"}

    spf_records = [r for r in txt_records if r.lower().startswith("v=spf1")]

    if not spf_records:
        return {"status": "error", "message": f"No SPF record found for '{target}'."}

    # RFC 7208: publishing more than one SPF TXT record is itself a
    # "permerror" and breaks SPF entirely, even if each one looks valid.
    multiple_records_found = len(spf_records) > 1
    record = spf_records[0]
    tokens = record.split()[1:]  # drop the leading "v=spf1"
    mechanisms = [_parse_mechanism(t) for t in tokens]

    return {
        "status": "success",
        "result": {
            "domain": target,
            "raw_record": record,
            "multiple_records_found": multiple_records_found,
            "total_spf_records": len(spf_records),
            "mechanism_count": len(mechanisms),
            "mechanisms": mechanisms,
        },
    }
