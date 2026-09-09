"""Plan-tier entitlements  the single source of truth for WHICH services each
paid tier gets.

Why this exists: until now every gate in the codebase was the binary
`Subscription.is_premium` (see core.decorators.premium_required and
accounts.permissions.get_access_tier), so a $0.99 Lite subscriber received the
exact same services as a $3.00 Pro subscriber  everything except the monthly
Claude-credit grant, which was the only tier-aware entitlement. That silently
contradicted the published compare-plans matrix on pricing.html.

The matrix below mirrors that page row for row. Change a number here and the
gate, the /api/accounts/me/ payload, and the billing page all move together.

Deliberately NOT modelled here (nothing in the codebase can enforce them yet,
so inventing a gate would be dishonest):
  - "Email Deliverability Wizard"  no such tool exists; the closest shipped
    tools (spf_check/dmarc_check/dkim_check) are free local-tier tools.
  - "Priority processing"  there is no job queue to prioritise.
  - "Ad-free"  no ad script exists anywhere on the site yet.
  - "Early access"  no feature-preview mechanism exists.
Those four rows are still aspirational marketing copy; see the audit notes.
"""
from functools import wraps

from django.http import JsonResponse

# Ordered weakest → strongest. "premium" is the legacy plan value and maps to
# pro (same mapping payments.subscription_utils._PRICE_PLAN_TO_TIER uses).
PLAN_ORDER = ["free", "lite", "standard", "pro"]
_LEGACY_ALIASES = {"premium": "pro"}

# One row per plan, mirroring pricing.html's compare-plans table.
#   monitors               max active monitors (0 = feature locked)
#   security_grade_depth   teaser | basic | detailed | advanced (see redact_security_grade)
#   ai_crawler             (limit, period) for the AI-Crawler Checker; None = uncapped
#   dashboard              Workbench access (trial users get it via their pro trial)
ENTITLEMENTS = {
    "free": {
        "monitors": 0,
        "security_grade_depth": "teaser",
        "ai_crawler": (3, "week"),
        "dashboard": False,
    },
    "lite": {
        "monitors": 0,
        "security_grade_depth": "basic",
        "ai_crawler": (30, "month"),
        "dashboard": True,
    },
    "standard": {
        "monitors": 3,
        "security_grade_depth": "detailed",
        "ai_crawler": (100, "month"),
        "dashboard": True,
    },
    "pro": {
        # "Unlimited" on the pricing page, with the footnoted fair-use brake.
        "monitors": 10,
        "security_grade_depth": "advanced",
        "ai_crawler": (20, "hour"),
        "dashboard": True,
    },
}

# Customer-facing plan names, for error copy and upgrade CTAs.
PLAN_LABELS = {"free": "Free", "lite": "Lite", "standard": "Standard", "pro": "Pro"}


def normalize_plan(plan):
    plan = _LEGACY_ALIASES.get(plan, plan)
    return plan if plan in ENTITLEMENTS else "free"


def monetization_enabled():
    """Is the paywall switched on? Off until the Lenco payment API key is
    available  see core.middleware's `monetization` flag. While off, every
    logged-in account is treated as Pro (open-source mode)."""
    from core.middleware import flag_enabled

    return flag_enabled("monetization")


def get_plan(user):
    """The plan whose entitlements this user is entitled to RIGHT NOW.

    Reads through Subscription.is_premium rather than .plan directly, so an
    expired/cancelled subscription (or a lapsed trial, which is_premium expires
    lazily) correctly falls back to free instead of leaving a stale paid plan
    string granting paid services.

    While the `monetization` flag is off (open-source mode), any logged-in
    account is treated as "pro" regardless of its real Subscription  the
    platform can't take payment right now, so nothing should be paywalled.
    """
    if not getattr(user, "is_authenticated", False):
        return "free"
    if not monetization_enabled():
        return "pro"
    sub = getattr(user, "subscription", None)
    if not (sub and sub.is_premium):
        return "free"
    return normalize_plan(sub.plan)


def is_premium_effective(user):
    """Boolean shim for call sites that only need a yes/no premium check
    (core.decorators.premium_required, accounts.permissions.get_access_tier,
    the raw is_premium fields on /api/accounts/me/ and /billing/). Derives
    from get_plan() so open-source mode is honored everywhere consistently."""
    return get_plan(user) != "free"


def plan_rank(plan):
    return PLAN_ORDER.index(normalize_plan(plan))


def has_plan(user, minimum):
    return plan_rank(get_plan(user)) >= plan_rank(minimum)


def entitlement(user, key):
    """The value of one entitlement for this user's current plan."""
    return ENTITLEMENTS[get_plan(user)][key]


def entitlements_json(user):
    """The whole row, for /api/accounts/me/  lets the frontend show honest
    caps ("3 of 3 monitors used") instead of hardcoding numbers per page."""
    plan = get_plan(user)
    row = ENTITLEMENTS[plan]
    limit, period = row["ai_crawler"] if row["ai_crawler"] else (None, None)
    return {
        "plan": plan,
        "monitors": row["monitors"],
        "security_grade_depth": row["security_grade_depth"],
        "ai_crawler_limit": limit,
        "ai_crawler_period": period,
        "dashboard": row["dashboard"],
    }


def requires_plan(minimum):
    """Gate a view behind a MINIMUM plan tier.

    Mirrors core.decorators.premium_required's contract exactly (401 when
    logged out, 402 when under-entitled, same upgrade_url) so frontend error
    handling keeps working unchanged  it just also reports which plan is
    needed, so the UI can name the right upgrade.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({"error": "login_required", "upgrade_url": "/pricing.html"}, status=401)
            if not has_plan(request.user, minimum):
                label = PLAN_LABELS[normalize_plan(minimum)]
                return JsonResponse(
                    {
                        "error": "premium_required",
                        "required_plan": normalize_plan(minimum),
                        "current_plan": get_plan(request.user),
                        "upgrade_url": "/pricing.html",
                        "message": f"This feature is included from the {label} plan up.",
                    },
                    status=402,
                )
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


# --- Security Grade depth ------------------------------------------------
# The composite scan always runs in full; what differs per tier is how much of
# the report body survives into the response. This is a real server-side
# redaction (the network tab never sees the hidden rows), matching the existing
# free-teaser behaviour in network_tools.views.
_DEPTH_SEVERITIES = {
    "basic": ("alert",),
    "detailed": ("alert", "warning"),
    "advanced": ("alert", "warning", "info"),
}


def redact_security_grade(result, depth):
    """Return `result` trimmed to `depth`. Never mutates the input."""
    if depth == "advanced":
        return result

    teaser = {
        "target": result.get("target"),
        "grade": result.get("grade"),
        "score": result.get("score"),
        "scored_at": result.get("scored_at"),
    }
    if depth == "teaser":
        return {**teaser, "locked": True}

    allowed = _DEPTH_SEVERITIES[depth]
    findings = result.get("findings") or []
    shown = [f for f in findings if f.get("severity") in allowed]
    return {
        **teaser,
        "findings": shown,
        # Honest about what's being withheld rather than pretending the report
        # is complete  the count is what drives the "upgrade to see N more" CTA.
        "findings_hidden": len(findings) - len(shown),
        "depth": depth,
        "locked": len(findings) > len(shown),
    }
