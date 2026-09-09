"""
Shared helper for the email authentication checkers (SPF, DKIM, DMARC)  all
three are "fetch a TXT record set at some name, then match a prefix" under
the hood. Factored out here instead of repeating the same DNS-fetch-and-
decode logic three times, per the project roadmap's own note that these
tools share enough logic to be worth it.
"""
import dns.resolver
import dns.exception


class DomainNotFound(Exception):
    def __init__(self, name):
        super().__init__(f"'{name}' does not exist.")
        self.name = name


class LookupTimedOut(Exception):
    def __init__(self, name):
        super().__init__(f"DNS query for '{name}' timed out.")
        self.name = name


def fetch_txt_records(name):
    """
    Returns a list of decoded TXT record strings for `name` (empty list if
    the name exists but publishes no TXT records). Raises DomainNotFound or
    LookupTimedOut so callers can produce tool-specific error messages.
    """
    try:
        answer = dns.resolver.resolve(name, "TXT")
    except dns.resolver.NXDOMAIN:
        raise DomainNotFound(name)
    except dns.resolver.NoAnswer:
        return []
    except dns.exception.Timeout:
        raise LookupTimedOut(name)

    records = []
    for rdata in answer:
        # dnspython splits TXT values over 255 bytes into multiple strings;
        # rejoin them before matching against a prefix like "v=spf1".
        joined = b"".join(rdata.strings).decode("utf-8", errors="replace")
        records.append(joined)
    return records


def parse_tag_list(record, separator=";"):
    """Parses a 'k1=v1; k2=v2' style record (used by DKIM and DMARC) into a dict."""
    tags = {}
    for part in record.split(separator):
        part = part.strip()
        if "=" in part:
            key, value = part.split("=", 1)
            tags[key.strip().lower()] = value.strip()
    return tags
