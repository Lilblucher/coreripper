"""Feature-flag kill switches, flipped from the admin engine room.

Each entry maps an API path prefix to a FeatureFlag key. When a flag is off,
every request under its prefixes gets a 503 feature_disabled JSON response.
Superusers bypass every gate (so features stay testable while switched off),
and admin/auth/me endpoints are deliberately unmapped so a superuser can
never lock themselves out of the cockpit.

Flag lookups are cached for a few seconds to avoid a DB hit per request;
the admin toggle endpoint clears the cache so a flipped switch takes effect
immediately.

Not every flag is a path prefix. `claude_ai` gates a *model*, not an endpoint
the three AI-tool endpoints and the Workbench must keep serving the free model
while Sonnet-5 is off  so it lives in FLAG_DEFS (to get its Engine Room switch)
but deliberately never in PREFIX_FLAGS. Code that needs it calls flag_enabled()
directly: credits.services.run_ai and payments.views (credit-pack checkout).
"""
import logging

from django.core.cache import cache
from django.http import JsonResponse

logger = logging.getLogger(__name__)

FLAG_CACHE_KEY = "core_feature_flags_v1"
FLAG_CACHE_SECONDS = 5

# Prefix → flag key. Longest-prefix-first so more specific rules win
# (e.g. /api/accounts/google-login/ before any broader /api/accounts/ rule).
PREFIX_FLAGS = [
    ("/api/accounts/signup/", "signups"),
    ("/api/accounts/google-login/", "google_login"),
    ("/api/accounts/forgot-password/", "password_reset"),
    ("/api/accounts/reset-password/", "password_reset"),
    ("/api/accounts/support/", "support_tickets"),
    ("/api/toolbox/", "network_tools"),
    ("/api/ai-tools/", "ai_tools"),
    ("/api/dashboard/", "workbench"),
    ("/api/monitors/", "monitoring"),
    ("/api/payments/", "payments"),
    ("/api/blog/posts/", "blog"),
    ("/api/blog/categories/", "blog"),
]

# key → (label, description). The data migration seeds from this, and the
# admin features endpoint uses it to self-heal missing rows.
FLAG_DEFS = {
    "signups": ("New signups", "Account creation via the signup form."),
    "google_login": ("Google sign-in", "Login/signup with a Google account."),
    "password_reset": ("Password reset", "Forgot-password emails and reset codes."),
    "support_tickets": ("Support tickets", "Ticket submission from the support page."),
    "network_tools": ("Network tools", "All server-side network tool lookups (DNS, SSL, WHOIS…)."),
    "ai_tools": ("AI tools", "Premium AI endpoints (tutor, quiz generator, coding helper)."),
    "workbench": ("Workbench", "The premium dashboard: projects, saved results, assistant."),
    "monitoring": ("Monitoring", "Scheduled monitors, checks and alert history."),
    "payments": ("Payments", "Charge creation and payment verification."),
    "blog": ("Public blog", "Public article and category feeds (admin authoring is never blocked)."),
    "claude_ai": (
        "Sonnet-5 AI",
        "The paid AI model and credit-pack sales. Off until Anthropic API credits are funded "
        "free Livia AI keeps working; every Sonnet-5 surface reads as “still being worked on”.",
    ),
    "monetization": (
        "Monetization",
        "Premium tiers & payments. OFF = open-source mode: every logged-in account gets full "
        "Pro-tier access for free, and pricing/checkout UI is hidden. ON = normal paywall. Off "
        "until the Lenco payment API key is available.",
    ),
}

# Flags that ship OFF. Everything else defaults on, and a missing row counts as
# enabled (flags fail open) — but claude_ai and monetization fail *closed*: a
# fresh database silently going live on a paid API (claude_ai) or silently
# paywalling a site that can't yet take payments (monetization) are both
# failure modes worse than the alternative. `_ensure_flags()` self-heals to
# this default too.
FLAG_DEFAULTS = {"claude_ai": False, "monetization": False}

# Flags whose state the static frontend is allowed to read, unauthenticated, via
# GET /api/features/ — so a page can grey out a switched-off feature instead of
# offering a click that only 503s. Never widen this to the whole table: the rest
# of the keys are operational detail.
PUBLIC_FLAGS = ("claude_ai", "monetization")


def flag_enabled(key):
    """Is this feature switched on? Used by code paths that a path-prefix rule
    can't express (see the module docstring). Callers own their own bypass
    policy — unlike the middleware, this makes no superuser exception."""
    return _load_flags().get(key, FLAG_DEFAULTS.get(key, True))


def _flags_from_db():
    from .models import FeatureFlag

    return dict(FeatureFlag.objects.values_list("key", "enabled"))


def _load_flags():
    """Read the flag table, cached for FLAG_CACHE_SECONDS.

    The cache is a latency optimisation, not the source of truth. This
    middleware runs on *every* /api/ request, so letting a cache-backend
    outage propagate takes the entire API down with it - a Redis outage
    once turned every endpoint into a 500 (signup, stats, pricing, news),
    which reads to users as "the whole site is broken" rather than "one
    dependency is down". A connection error therefore degrades to reading
    the DB directly. FLAG_DEFAULTS still applies on that path, so claude_ai
    keeps failing closed and never starts spending on a cache blip.
    """
    try:
        flags = cache.get(FLAG_CACHE_KEY)
    except Exception:
        logger.warning(
            "feature-flag cache unavailable; falling back to DB", exc_info=True
        )
        return _flags_from_db()

    if flags is None:
        flags = _flags_from_db()
        try:
            cache.set(FLAG_CACHE_KEY, flags, FLAG_CACHE_SECONDS)
        except Exception:
            # Readable but uncacheable is fine - just slower, not broken.
            logger.warning("feature-flag cache write failed", exc_info=True)
    return flags


class FeatureFlagMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/api/"):
            for prefix, key in PREFIX_FLAGS:
                if path.startswith(prefix):
                    # Missing row counts as enabled (except FLAG_DEFAULTS).
                    if flag_enabled(key) is False and not request.user.is_superuser:
                        label = FLAG_DEFS.get(key, (key,))[0]
                        return JsonResponse(
                            {
                                "error": "feature_disabled",
                                "feature": key,
                                "message": f"{label} is temporarily switched off by the administrators.",
                            },
                            status=503,
                        )
                    break
        return self.get_response(request)
