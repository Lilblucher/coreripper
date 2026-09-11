"""
ASN Lookup tool.

Resolves a domain or IP to its Autonomous System info (ASN, org, country,
registry, allocation date, prefix/route) via RDAP  the IANA-backed,
officially-standardized replacement for WHOIS (RFC 7480-7484). Queries go
directly to the authoritative regional registry (ARIN, RIPE, APNIC, LACNIC,
AFRINIC), no third-party API or API key involved.

Requires: pip install ipwhois --break-system-packages

NOTE: an earlier version of this module used BGPView's free API
(api.bgpview.io). That service was permanently shut down on 2025-11-26, so
it's been replaced with this RDAP-based approach instead.
"""

import ipaddress
import socket

from ipwhois import IPWhois
from ipwhois.exceptions import ASNRegistryError, HTTPLookupError, IPDefinedError


def _is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _resolve_to_ip(target):
    """Return an IP for the given target, raising socket.gaierror if a
    hostname won't resolve."""
    if _is_ip(target):
        return target
    return socket.gethostbyname(target)


def get_asn_info(target):
    target = (target or "").strip()
    if not target:
        return {"status": "error", "message": "No target provided."}

    try:
        ip = _resolve_to_ip(target)
    except socket.gaierror:
        return {"status": "error", "message": f"Could not resolve hostname: {target}"}

    try:
        obj = IPWhois(ip)
        rdap = obj.lookup_rdap(depth=1)
    except IPDefinedError:
        return {
            "status": "error",
            "message": f"{ip} is a private/reserved IP address and has no public ASN.",
        }
    except (ASNRegistryError, HTTPLookupError) as e:
        return {"status": "error", "message": f"RDAP lookup failed: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error during ASN lookup: {e}"}

    network = rdap.get("network") or {}
    asn_number = rdap.get("asn")
    prefix = rdap.get("asn_cidr") or network.get("cidr")
    registry = rdap.get("asn_registry")

    result = {
        "query": target,
        "resolved_ip": ip,
        "asn": f"AS{asn_number}" if asn_number else None,
        "organization": rdap.get("asn_description") or network.get("name"),
        "country": rdap.get("asn_country_code"),
        "registry": registry.upper() if registry else None,
        "allocation_date": rdap.get("asn_date"),
        "prefix": prefix,
        "route": prefix,  # RDAP doesn't distinguish an announced BGP route from the allocated block
    }

    return {"status": "success", "result": result}