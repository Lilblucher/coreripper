"""
TLS Version Checker  probes a host for which TLS/SSL protocol versions it
will negotiate, plus the cipher suite each version settles on.

Important nuance handled here: modern OpenSSL builds (3.0+) refuse to even
*offer* TLS 1.0 / TLS 1.1 by default at the client library level, separate
from whatever the server supports  a plain handshake attempt fails with
NO_PROTOCOLS_AVAILABLE before a single byte reaches the server. Left alone,
this tool would report every server as "not supporting" those versions
regardless of reality. We work around this by lowering OpenSSL's security
level (SECLEVEL=0) before attempting the legacy-protocol handshakes, so a
"No" result reflects a genuine server-side rejection (a TLS alert), not our
own client refusing to try. Verified against a live server: without the
SECLEVEL relaxation the failure is NO_PROTOCOLS_AVAILABLE (client-side);
with it, a real server that has TLS 1.0/1.1 turned off returns a proper
TLSV1_ALERT_PROTOCOL_VERSION (server-side).

SSL 3.0 has no such workaround  most modern OpenSSL builds are compiled
with SSLv3 support removed entirely (no-ssl3), which SECLEVEL can't
override. SSL 2.0 isn't in Python's ssl.TLSVersion enum at all; it was
dropped from OpenSSL outright years ago. Both are reported honestly as
"untestable from this server" (supported = None) rather than a misleadingly
confident "No"  this is a scanner limitation, not a finding.
"""
import ssl
import socket

# (display name, TLSVersion enum member, strength classification)
# Strength is a fixed property of the protocol itself, not of the result.
_PROTOCOLS = [
    ("TLS 1.3", ssl.TLSVersion.TLSv1_3, "strong"),
    ("TLS 1.2", ssl.TLSVersion.TLSv1_2, "strong"),
    ("TLS 1.1", ssl.TLSVersion.TLSv1_1, "deprecated"),
    ("TLS 1.0", ssl.TLSVersion.TLSv1, "deprecated"),
    ("SSL 3.0", ssl.TLSVersion.SSLv3, "insecure"),
]


def _try_handshake(host, port, version, timeout=6):
    """
    Returns (supported, detail):
      supported=True  -> detail is the negotiated cipher tuple
      supported=False -> detail is the server's rejection message
      supported=None  -> untestable from this client; detail explains why
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = version
    ctx.maximum_version = version
    try:
        # Let the client offer old/weak protocols so a rejection is the
        # SERVER's decision, not a client-side refusal to even try.
        ctx.set_ciphers("DEFAULT@SECLEVEL=0")
    except ssl.SSLError as e:
        return None, f"Client TLS library can't attempt this protocol: {e}"

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                return True, ssock.cipher()
    except ssl.SSLError as e:
        if "NO_PROTOCOLS_AVAILABLE" in str(e):
            return None, "This server's TLS library build doesn't support this protocol on the client side, so it can't be tested."
        return False, str(e)
    except (ConnectionError, socket.timeout, OSError) as e:
        return False, str(e)


def check_tls_versions(target, port=443):
    target = (target or "").strip()
    if not target:
        return {"status": "error", "message": "Please provide a domain."}

    # Strip scheme/path/port if someone pastes a full URL
    host = target.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]

    rows = []
    any_success = False
    any_real_attempt = False

    for name, version, strength in _PROTOCOLS:
        supported, detail = _try_handshake(host, port, version)
        if supported is True:
            any_success = True
            any_real_attempt = True
        elif supported is False:
            any_real_attempt = True

        rows.append({
            "version": name,
            "supported": supported,  # True / False / None
            "cipher_suite": detail[0] if supported is True else None,
            "strength": strength,
            "note": detail if supported is not True else None,
        })

    # SSL 2.0  not representable via ssl.TLSVersion at all in modern Python/OpenSSL
    rows.append({
        "version": "SSL 2.0",
        "supported": None,
        "cipher_suite": None,
        "strength": "insecure",
        "note": "SSLv2 was removed from OpenSSL years ago and can't be tested by this or any modern TLS client. Treat any server that still offers it as critically insecure.",
    })

    if not any_real_attempt:
        return {
            "status": "error",
            "message": f"Could not establish any TLS connection to {host}:{port}. Check the hostname and port.",
        }

    return {
        "status": "success",
        "result": {"host": host, "port": port, "checks": rows},
    }