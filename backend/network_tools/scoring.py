"""
Security Grade  composite scoring for network_tools.views's "security_grade"
dispatcher branch. Aggregates results already produced by the individual
tool functions (security_headers, tls_version_checker, ssl_expiration,
cors_checker, spf_checker, dmarc_checker, dkim_checker, dnssec_checker,
cookie_checker) into a single letter grade + itemized findings.

Deliberately transparent, documented deductions (not an opaque formula) 
this is the whole point of the feature per the product's honesty stance.
Each sub-check's result may itself be `{"status": "error", ...}` (e.g. the
domain doesn't resolve, or a DKIM selector guess is wrong)  that is NOT
treated as a security failure, since we can't penalize what we couldn't
observe. Instead it's surfaced as a low-severity "could not verify" info
finding, and no points are deducted for that section.
"""
from datetime import datetime, timezone


def points_to_grade(points):
    if points >= 95:
        return "A+"
    if points >= 85:
        return "A"
    if points >= 75:
        return "B"
    if points >= 65:
        return "C"
    if points >= 50:
        return "D"
    return "F"


def _ok(sub_result):
    return isinstance(sub_result, dict) and sub_result.get("status") == "success"


def score_security_grade(headers, tls, ssl_exp, cors, spf, dmarc, dkim, dnssec, cookies):
    findings = []
    points = 100  # start at perfect, deduct per issue  transparent and documented

    # --- HTTP security headers (security_headers.py already scores itself) ---
    if _ok(headers):
        h = headers["result"]
        missing = [row["header"] for row in h.get("headers", []) if not row.get("present")]
        # Reuse the tool's own weighted score rather than re-deriving one 
        # scale its 0-100 into a deduction out of 20 (headers' own share here).
        header_score = h.get("score", 100)
        deduction = round((100 - header_score) * 0.20)
        points -= deduction
        for name in missing:
            findings.append({"severity": "warning", "item": name, "message": f"Missing {name} header"})
    else:
        findings.append({"severity": "info", "item": "HTTP headers", "message": "Could not verify security headers (site unreachable)"})

    # --- TLS version ---
    if _ok(tls):
        checks = tls["result"].get("checks", [])
        outdated_supported = [c["version"] for c in checks if c.get("supported") is True and c.get("strength") in ("deprecated", "insecure")]
        if outdated_supported:
            points -= 20
            findings.append({"severity": "alert", "item": "TLS version",
                              "message": f"Outdated TLS version(s) accepted: {', '.join(outdated_supported)}"})
    else:
        findings.append({"severity": "info", "item": "TLS version", "message": "Could not verify TLS versions (connection failed)"})

    # --- SSL cert validity/expiry ---
    if _ok(ssl_exp):
        s = ssl_exp["result"]
        days = s.get("days_remaining", 999)
        status = s.get("cert_status")
        if status == "expired":
            points -= 20
            findings.append({"severity": "alert", "item": "SSL certificate", "message": "Certificate has expired"})
        elif days < 14:
            points -= 10
            findings.append({"severity": "warning", "item": "SSL certificate", "message": f"Certificate expires in {days} days"})
    else:
        findings.append({"severity": "info", "item": "SSL certificate", "message": "Could not verify SSL certificate (handshake failed)"})

    # --- CORS misconfiguration ---
    if _ok(cors):
        c = cors["result"]
        wildcard_with_credentials = c.get("allow_origin") == "*" and str(c.get("allow_credentials", "")).lower() == "true"
        if wildcard_with_credentials:
            points -= 15
            findings.append({"severity": "alert", "item": "CORS", "message": "Wildcard origin allowed with credentials"})
    else:
        findings.append({"severity": "info", "item": "CORS", "message": "Could not verify CORS configuration"})

    # --- Email auth (SPF/DMARC/DKIM)  each missing = deduction ---
    if _ok(spf):
        if not spf["result"].get("raw_record"):
            points -= 10
            findings.append({"severity": "warning", "item": "SPF", "message": "No SPF record found"})
    else:
        points -= 10
        findings.append({"severity": "warning", "item": "SPF", "message": "No SPF record found"})

    if _ok(dmarc):
        if not dmarc["result"].get("raw_record"):
            points -= 10
            findings.append({"severity": "warning", "item": "DMARC", "message": "No DMARC record found"})
    else:
        points -= 10
        findings.append({"severity": "warning", "item": "DMARC", "message": "No DMARC record found"})

    # DKIM selectors aren't guessable  a lookup failure is much more often a
    # wrong-selector false negative than proof DKIM is absent, so this stays
    # "info" severity and a light deduction regardless of which failure mode.
    if not (_ok(dkim) and dkim["result"].get("public_key_present")):
        points -= 5
        findings.append({"severity": "info", "item": "DKIM", "message": "No DKIM record found (selector-dependent, may be a false negative)"})

    # --- DNSSEC ---
    if _ok(dnssec):
        if not dnssec["result"].get("signed"):
            points -= 5
            findings.append({"severity": "info", "item": "DNSSEC", "message": "DNSSEC not enabled"})
    else:
        findings.append({"severity": "info", "item": "DNSSEC", "message": "Could not verify DNSSEC status"})

    # --- Cookie flags ---
    if _ok(cookies):
        cr = cookies["result"]
        if cr.get("cookies_found") and (cr.get("missing_secure_flag") or cr.get("missing_httponly_flag")):
            points -= 5
            findings.append({"severity": "warning", "item": "Cookies", "message": "Cookies missing Secure/HttpOnly flags"})
    else:
        findings.append({"severity": "info", "item": "Cookies", "message": "Could not verify cookie flags"})

    points = max(points, 0)
    grade = points_to_grade(points)

    return {
        "target": None,  # filled by caller
        "grade": grade,
        "score": points,
        "findings": sorted(findings, key=lambda f: {"alert": 0, "warning": 1, "info": 2}[f["severity"]]),
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
