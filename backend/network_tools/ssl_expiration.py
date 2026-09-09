from datetime import datetime, timezone

from .ssl_certs import get_ssl_info


def _get_common_name(field):
    """Extract commonName from getpeercert()'s nested subject/issuer tuples."""
    try:
        for group in field:
            for k, v in group:
                if k == "commonName":
                    return v
    except Exception:
        return None
    return None


def get_ssl_expiration(domain):
    cert_response = get_ssl_info(domain)
    if cert_response.get("status") != "success":
        return cert_response  # bubble up the original connection/handshake error

    cert = cert_response["result"]
    not_after = cert.get("notAfter")
    not_before = cert.get("notBefore")

    if not not_after:
        return {"status": "error", "message": f"Could not read certificate expiration for '{domain}'."}

    try:
        # OpenSSL format: "Jun 15 00:00:00 2026 GMT"
        expiry_date = datetime.strptime(
            not_after.replace(" GMT", ""), "%b %d %H:%M:%S %Y"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return {"status": "error", "message": f"Could not parse certificate expiration date: '{not_after}'."}

    days_remaining = (expiry_date - datetime.now(timezone.utc)).days

    if days_remaining < 0:
        cert_status = "expired"
    elif days_remaining <= 14:
        cert_status = "critical"
    elif days_remaining <= 30:
        cert_status = "warning"
    else:
        cert_status = "valid"

    return {
        "status": "success",
        "result": {
            "domain": domain,
            "common_name": _get_common_name(cert.get("subject")) or domain,
            "issuer": _get_common_name(cert.get("issuer")),
            "valid_from": not_before,
            "valid_to": not_after,
            "days_remaining": days_remaining,
            "cert_status": cert_status,
        }
    }