from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_GET
from django.core.cache import cache
from .dns_lookup import dns_lookup
from .ip_info import get_ip_info
from .header_reader import get_http_headers
from .ssl_certs import get_ssl_info
from .whoiz import get_whois_info
from .ping_tool import get_ping_info
from .traceroute_tool import get_traceroute
from .port_scanner import scan_ports
from .ip_geo import get_ip_geo_info
from .security_headers import get_security_headers
from .ssl_expiration import get_ssl_expiration
from .asn_lookup import get_asn_info
from .tls_version_checker import check_tls_versions
from .rev_ip import get_reverse_ip
from .ip_blacklist_checker import get_blacklist_status
from .mac_address import get_mac_vendor
from .web_screenshot import capture_screenshot
from .cors_checker import check_cors
from .dns_propagation import get_dns_propagation
from .reverse_dns import get_reverse_dns
from .nameserver_lookup import get_nameservers
from .dnssec_checker import get_dnssec_status
from .mx_lookup import get_mx_records
from .spf_checker import get_spf_record
from .dkim_checker import get_dkim_record
from .dmarc_checker import get_dmarc_record
from .redirect_checker import get_redirect_chain
from .http_status_checker import get_http_status
from .uptime_checker import check_uptime
from .open_graph_checker import get_open_graph_tags
from .robots_checker import test_robots_txt
from .sitemap_validator import validate_sitemap
from .scam_detector import scan_message
from .cookie_checker import check_cookie_flags
from .scoring import score_security_grade
from .ai_crawler_checker import check_ai_crawlers
from .ipv6_readiness import check_ipv6_readiness

from accounts import trial as guest_trial
from accounts.entitlements import ENTITLEMENTS, PLAN_LABELS, get_plan, redact_security_grade
from accounts.permissions import get_access_tier, get_tool_tier


def _port_scan_host(target):
    """Extract the bare host from a Port Scanner target for the localhost check."""
    return (target or "").strip().lower().split("://")[-1].split("/")[0].split(":")[0]


def run_tool_internal(tool, target, selector="default", path="/", user_agent="*", region_hint=""):
    """The same tool_key dispatch table as network_toolbox_view, extracted so
    Celery tasks (monitors/tasks.py) can call it as a plain function  no
    HttpResponse, no access gate (monitors are already Premium-gated at the
    view layer before a check is ever scheduled), no request object needed.
    Never make an HTTP request to this same server from inside a Celery task;
    call this directly instead.

    Returns the same plain dict network_toolbox_view would put in
    response_data, or {"status": "error", "message": ...} for an unknown tool.
    """
    if tool == 'dns':
        return dns_lookup(target)
    elif tool == 'ip_info':
        return get_ip_info(target)
    elif tool == 'headers':
        return get_http_headers(target)
    elif tool == 'ssl_info':
        return get_ssl_info(target)
    elif tool == 'whois':
        return get_whois_info(target)
    elif tool == 'ping':
        return get_ping_info(target)
    elif tool == 'port_scan':
        return scan_ports(target)
    elif tool == 'traceroute':
        return get_traceroute(target)
    elif tool == 'ip_geo':
        return get_ip_geo_info(target)
    elif tool == 'ssl_expiration':
        return get_ssl_expiration(target)
    elif tool == 'security_headers':
        return get_security_headers(target)
    elif tool == 'ip_blacklist':
        return get_blacklist_status(target)
    elif tool == 'mac_lookup':
        return get_mac_vendor(target)
    elif tool == 'asn_lookup':
        return get_asn_info(target)
    elif tool == 'reverse_ip':
        return get_reverse_ip(target)
    elif tool == 'web_screenshot':
        return capture_screenshot(target)
    elif tool == 'cors_check':
        return check_cors(target)
    elif tool == 'tls_check':
        return check_tls_versions(target)
    elif tool == 'dns_propagation':
        return get_dns_propagation(target)
    elif tool == 'reverse_dns':
        return get_reverse_dns(target)
    elif tool == 'nameserver_lookup':
        return get_nameservers(target)
    elif tool == 'dnssec_check':
        return get_dnssec_status(target)
    elif tool == 'mx_lookup':
        return get_mx_records(target)
    elif tool == 'spf_check':
        return get_spf_record(target)
    elif tool == 'dkim_check':
        return get_dkim_record(target, selector)
    elif tool == 'dmarc_check':
        return get_dmarc_record(target)
    elif tool == 'redirect_check':
        return get_redirect_chain(target)
    elif tool == 'http_status':
        return get_http_status(target)
    elif tool == 'uptime_check':
        return check_uptime(target)
    elif tool == 'og_check':
        return get_open_graph_tags(target)
    elif tool == 'robots_check':
        return test_robots_txt(target, path, user_agent)
    elif tool == 'sitemap_validate':
        return validate_sitemap(target)
    elif tool == 'scam_detector':
        return scan_message(target, region_hint)
    elif tool == 'security_grade':
        headers = run_tool_internal('security_headers', target)
        tls = run_tool_internal('tls_check', target)
        ssl_exp = run_tool_internal('ssl_expiration', target)
        cors = run_tool_internal('cors_check', target)
        spf = run_tool_internal('spf_check', target)
        dmarc = run_tool_internal('dmarc_check', target)
        dkim = run_tool_internal('dkim_check', target)
        dnssec = run_tool_internal('dnssec_check', target)
        cookies = check_cookie_flags(target)
        result = score_security_grade(headers, tls, ssl_exp, cors, spf, dmarc, dkim, dnssec, cookies)
        result['target'] = target
        return {"status": "success", "result": result}
    elif tool == 'ai_crawler_check':
        return check_ai_crawlers(target)
    elif tool == 'ipv6_readiness':
        return check_ipv6_readiness(target)
    else:
        return {"status": "error", "message": f"Unknown tool '{tool}'."}


@require_GET
def network_toolbox_view(request):
    tool = request.GET.get('tool')
    target = request.GET.get('target')

    if not tool or not target:
        return JsonResponse({
            "status": "error",
            "message": "Missing 'tool' or 'target' query parameters"
        }, status=400)

    # --- Access gate: Guest (3 ops/tool) / Free (local only) / Premium (all) ---
    # Runs before any real work. See accounts/permissions.py + accounts/trial.py
    # and ACCESS_MATRIX_HANDOFF.md. Dev tools run client-side so aren't gated
    # here; AI tools dispatch through core/ and are gated separately.
    access_tier = get_access_tier(request)      # guest | free | premium
    tool_tier = get_tool_tier(tool)             # local | api

    # Port Scanner misuse guard (independent of pricing): scanning a remote host
    # needs at least a Free account; localhost/loopback is always allowed.

   # if tool == 'port_scan' and access_tier == 'guest':
    #    if _port_scan_host(target) not in ('localhost', '127.0.0.1', '::1', ''):
     #       return JsonResponse({
      #          "status": "error", "error": "login_required", "upgrade_url": "/login.html",
       #         "message": "Create a free account to scan remote hosts.",
        #    }, status=401)
        
    # `access` metadata rides along on successful responses so tool pages can
    # show honest "N left" hints without a second request.
    plan = get_plan(request.user)               # free | lite | standard | pro
    access_meta = {"tier": access_tier, "plan": plan}

    # Per-plan cap on the AI-Crawler Checker (pricing.html: 3/week Free,
    # 30/mo Lite, 100/mo Standard, 20/hr Pro fair use). Runs for logged-in
    # users of every plan; guests stay on the 3-op-per-tool guest trial below.
    if tool == "ai_crawler_check" and request.user.is_authenticated:
        limit, period = ENTITLEMENTS[plan]["ai_crawler"]
        allowed, remaining = guest_trial.check_and_increment_tool_quota(
            request.user, tool, limit, period
        )
        if not allowed:
            per = {"hour": "this hour", "week": "this week", "month": "this month"}[period]
            return JsonResponse({
                "status": "error", "error": "tool_quota_exhausted", "upgrade_url": "/pricing.html",
                "current_plan": plan,
                "message": f"You've used all {limit} AI-Crawler checks for {per} on the "
                           f"{PLAN_LABELS[plan]} plan. Upgrade for a higher limit.",
            }, status=429)
        access_meta["tool_quota_remaining"] = remaining

    if access_tier == 'premium':
        pass  # full access to everything
    elif access_tier == 'free':
        if tool_tier == 'api':
            return JsonResponse({
                "status": "error", "error": "premium_required", "upgrade_url": "/pricing.html",
                "message": "This tool uses an external API and needs a Premium subscription.",
            }, status=402)
        allowed, remaining = guest_trial.check_and_increment_free_quota(request.user)
        if not allowed:
            return JsonResponse({
                "status": "error", "error": "free_quota_exhausted", "upgrade_url": "/pricing.html",
                "message": f"You've used all {guest_trial.FREE_DAILY_OP_LIMIT} free operations for today. "
                           "Upgrade to Premium for unlimited use, or come back tomorrow.",
            }, status=429)
        access_meta["quota_remaining"] = remaining
    else:  # guest
        anon_id = guest_trial.get_anon_id(request)
        if not guest_trial.check_and_increment_trial(anon_id, tool):
            return JsonResponse({
                "status": "error", "error": "trial_exhausted", "upgrade_url": "/signup.html",
                "message": "You've used your 3 free tries for this tool. Create a free account to keep going.",
            }, status=401)
        access_meta["trial_remaining"] = guest_trial.trial_remaining(anon_id, tool)
    # --------------------------------------------------------------------------

    response_data = run_tool_internal(
        tool, target,
        selector=request.GET.get('selector', 'default'),
        path=request.GET.get('path', '/'),
        user_agent=request.GET.get('user_agent', '*'),
        region_hint=request.GET.get('region_hint', ''),
    )
    if response_data.get("message", "") == f"Unknown tool '{tool}'.":
        # This exact message only ever comes from run_tool_internal's own
        # fallback branch  a real tool's internal error (e.g. port_scan's
        # "Could not resolve domain: ...") must still get access_meta below
        # like a normal response, not be short-circuited as a 400.
        return JsonResponse(response_data, status=400)

    # Security Grade depth is graded by PLAN, not just paid/unpaid (pricing.html:
    # Teaser / Basic / Detailed / Advanced). Everyone including guests still gets
    # the real scan and grade/score  that's the conversion hook per the product
    # spec ("user sees a C+ and wants to know why"); what each tier buys is how
    # much of the report body survives. Redacted server-side, not visually
    # blurred, so no tier can be bypassed by reading the response.
    if tool == "security_grade" and response_data.get("status") == "success":
        depth = ENTITLEMENTS[plan]["security_grade_depth"]
        response_data["result"] = redact_security_grade(response_data.get("result") or {}, depth)

    if isinstance(response_data, dict):
        response_data["access"] = access_meta
    return JsonResponse(response_data)


# --- Security Grade shareable badge/card ---------------------------------
# The one pair of endpoints in this app that must work with NO bearer token
# at all  they're meant to be embedded (<img src=...>) in READMEs and other
# pages. No premium/tier gating; instead: a 1-hour per-target cache (so
# repeated embeds of the same badge never re-scan) plus a guest-style
# per-IP throttle (via the same primitive as every other guest limit) that
# only counts against a NEW target's first scan, to stop the no-auth route
# being used to bypass the normal guest trial.

_GRADE_COLORS = {"A+": "#10b981", "A": "#10b981", "B": "#10b981", "C": "#f59e0b", "D": "#f87171", "F": "#f87171"}


def _get_or_scan_security_grade(request, target):
    target = (target or "").strip()
    if not target:
        return None
    cache_key = f"secgrade_badge:{target.lower()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    anon_id = guest_trial.get_anon_id(request)
    if not guest_trial.check_and_increment_trial(anon_id, "security_grade_badge", limit=20):
        return {"status": "error", "message": "rate_limited"}
    result = run_tool_internal("security_grade", target)
    if result.get("status") == "success":
        cache.set(cache_key, result, 3600)
    return result


@require_GET
def security_grade_badge_svg(request):
    result = _get_or_scan_security_grade(request, request.GET.get("target", ""))
    if result and result.get("status") == "success":
        grade = result["result"]["grade"]
        color = _GRADE_COLORS.get(grade, "#9ca3af")
    else:
        grade, color = "?", "#6b7280"

    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="152" height="28">'
        '<rect width="152" height="28" rx="5" fill="#141414"/>'
        '<rect x="0.75" y="0.75" width="150.5" height="26.5" rx="4.25" fill="none" stroke="#2597E8" stroke-width="1.5" opacity="0.4"/>'
        '<text x="10" y="18" font-family="Arial, sans-serif" font-size="11" fill="#d1d5db">CoreRipper Security</text>'
        f'<text x="132" y="19" font-family="Arial, sans-serif" font-size="13" font-weight="bold" fill="{color}" text-anchor="middle">{grade}</text>'
        '</svg>'
    )
    resp = HttpResponse(svg, content_type="image/svg+xml")
    resp["Cache-Control"] = "public, max-age=3600"
    return resp


@require_GET
def security_grade_card_png(request):
    from PIL import Image, ImageDraw, ImageFont
    import io

    target = request.GET.get("target", "")
    result = _get_or_scan_security_grade(request, target)

    W, H = 600, 315
    img = Image.new("RGB", (W, H), "#0a0a0a")
    draw = ImageDraw.Draw(img)
    font_lg = ImageFont.load_default(size=64)
    font_md = ImageFont.load_default(size=22)
    font_sm = ImageFont.load_default(size=15)

    draw.rounded_rectangle([1, 1, W - 2, H - 2], radius=18, outline="#2597E8", width=2)

    if result and result.get("status") == "success":
        r = result["result"]
        grade, score = r["grade"], r["score"]
        color = _GRADE_COLORS.get(grade, "#9ca3af")
        draw.text((40, 40), "Security Grade", font=font_md, fill="#9ca3af")
        draw.text((40, 75), target, font=font_md, fill="#e5e7eb")
        draw.text((40, 130), grade, font=font_lg, fill=color)
        draw.text((40, 210), f"{score} / 100", font=font_sm, fill="#6b7280")
        top_findings = r.get("findings", [])[:3]
        y = 130
        for f in top_findings:
            draw.text((220, y), f"- {f['item']}", font=font_sm, fill="#d1d5db")
            y += 24
    else:
        draw.text((40, 130), "Scan unavailable", font=font_md, fill="#f87171")

    draw.text((40, H - 40), "coreripper.app", font=font_sm, fill="#2597E8")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    resp = HttpResponse(buf.getvalue(), content_type="image/png")
    resp["Cache-Control"] = "public, max-age=3600"
    return resp