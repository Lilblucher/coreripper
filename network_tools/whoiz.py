import whois


def _first(value):
    """python-whois often returns a list for fields that can have
    multiple values (e.g. multiple creation dates from different
    registrar records). Just take the first one."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _format_date(value):
    value = _first(value)
    if value is None:
        return None
    # python-whois returns datetime objects, not strings
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def get_whois_info(domain):
    try:
        w = whois.whois(domain)

        if not w or not w.domain_name:
            return {
                "status": "error",
                "message": f"No WHOIS record found for '{domain}'."
            }

        name_servers = w.name_servers
        if isinstance(name_servers, (list, tuple)):
            name_servers = [ns.lower() for ns in name_servers if ns]

        status = w.status
        if isinstance(status, (list, tuple)):
            status = ", ".join(status)

        return {
            "status": "success",
            "result": {
                "domain_name": _first(w.domain_name),
                "registrar": w.registrar,
                "created_date": _format_date(w.creation_date),
                "updated_date": _format_date(w.updated_date),
                "expiry_date": _format_date(w.expiration_date),
                "name_servers": name_servers,
                "status": status,
            }
        }
    except Exception as e:
        return {"status": "error", "message": f"WHOIS lookup failed: {str(e)}"}