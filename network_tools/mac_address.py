"""
MAC Address Lookup  resolves a MAC address's OUI prefix to a vendor name.

Two-tier lookup:
  1. Offline: the `manuf` package, which bundles Wireshark's maintained OUI
     database as a local file (no network call, no rate limit).
  2. Fallback: macvendors.com's free API (no key required) for any prefix
     the offline snapshot doesn't have yet.

Also detects "locally administered" MACs (the randomized addresses modern
phones/laptops use for privacy) and short-circuits with an explanation
instead of returning a meaningless vendor lookup.

Requires: pip install manuf --break-system-packages
"""
import re
import urllib.request
import urllib.error

from manuf import manuf

# Parsing the ~600KB OUI file is only worth doing once per process.
_parser = None


def _get_parser():
    global _parser
    if _parser is None:
        _parser = manuf.MacParser()
    return _parser


def _normalize_mac(raw):
    """Accepts colon, dash, dot, or bare hex formats. Returns AA:BB:CC:DD:EE:FF or None."""
    hex_only = re.sub(r'[^0-9A-Fa-f]', '', raw)
    if len(hex_only) != 12:
        return None
    hex_only = hex_only.upper()
    return ':'.join(hex_only[i:i + 2] for i in range(0, 12, 2))


def _is_locally_administered(mac):
    """
    Bit 1 (the 2nd-least-significant bit) of the first octet marks a MAC as
    locally administered rather than a factory-assigned vendor address.
    This is what iOS/Android "private Wi-Fi address" randomization sets.
    """
    first_octet = int(mac.split(':')[0], 16)
    return bool(first_octet & 0b00000010)


def _lookup_api(mac):
    """Returns a vendor string, None (not found), or raises RuntimeError('rate_limited')."""
    url = f"https://api.macvendors.com/{mac}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CoreRipper-NetworkTools/1.0"})
        with urllib.request.urlopen(req, timeout=6) as response:
            return response.read().decode("utf-8").strip()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 429:
            raise RuntimeError("rate_limited")
        return None
    except Exception:
        return None


def get_mac_vendor(target):
    raw = (target or "").strip()
    if not raw:
        return {"status": "error", "message": "Please provide a MAC address."}

    mac = _normalize_mac(raw)
    if not mac:
        return {
            "status": "error",
            "message": f"'{raw}' doesn't look like a valid MAC address (expected 12 hex digits, e.g. 00:1B:44:11:22:33).",
        }

    oui_prefix = ':'.join(mac.split(':')[:3])

    if _is_locally_administered(mac):
        return {
            "status": "success",
            "result": {
                "mac": mac,
                "oui_prefix": oui_prefix,
                "vendor": "Randomized / Locally Administered",
                "vendor_long": None,
                "registry": "N/A (private address)",
                "source": "detected",
                "note": (
                    "This MAC's locally-administered bit is set, meaning it's a randomized "
                    "or manually-assigned address (common on modern phones/laptops for "
                    "privacy) rather than a factory vendor address  vendor lookup doesn't apply."
                ),
            },
        }

    parser = _get_parser()
    vendor_short = parser.get_manuf(mac)
    vendor_long = parser.get_manuf_long(mac)

    if vendor_short:
        return {
            "status": "success",
            "result": {
                "mac": mac,
                "oui_prefix": oui_prefix,
                "vendor": vendor_short,
                "vendor_long": vendor_long,
                "registry": "IEEE OUI Database (offline)",
                "source": "local",
                "note": None,
            },
        }

    # Offline snapshot doesn't have it  try the live fallback
    try:
        api_vendor = _lookup_api(mac)
    except RuntimeError:
        return {
            "status": "error",
            "message": "Vendor not found in the offline database, and the fallback API is rate-limited right now. Try again in a moment.",
        }

    if api_vendor:
        return {
            "status": "success",
            "result": {
                "mac": mac,
                "oui_prefix": oui_prefix,
                "vendor": api_vendor,
                "vendor_long": None,
                "registry": "macvendors.com (live fallback)",
                "source": "api",
                "note": None,
            },
        }

    return {
        "status": "success",
        "result": {
            "mac": mac,
            "oui_prefix": oui_prefix,
            "vendor": "Unknown / Unregistered",
            "vendor_long": None,
            "registry": "Not found",
            "source": "none",
            "note": None,
        },
    }