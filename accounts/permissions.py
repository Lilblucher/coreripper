"""Access-tier resolution for the Guest / Free / Premium matrix.

NOTE: the access-matrix spec's sample `get_access_tier` reads
`request.user.is_premium`, which is WRONG in this codebase  `is_premium` is a
property on the `Subscription` model (`user.subscription.is_premium`), not on
`User`, so that version would always return "free". This is the corrected form,
consistent with `core.decorators.premium_required`.
"""

from core.models import Tool


def get_access_tier(request):
    """Return one of: 'guest' (not logged in), 'free' (logged in, no active
    subscription), 'premium' (logged in, active subscription).

    Reads through accounts.entitlements.is_premium_effective, so every
    logged-in account resolves to 'premium' while the site is in open-source
    mode (the `monetization` feature flag is off)  see entitlements.py."""
    from accounts.entitlements import is_premium_effective

    user = request.user
    if not user.is_authenticated:
        return "guest"
    return "premium" if is_premium_effective(user) else "free"


def get_tool_tier(tool_key):
    """Return 'local' or 'api' for a backend dispatch key, read from the
    admin-editable Tool registry.

    Unknown keys fall back to 'local' so a missing registry row never
    hard-locks a real free tool. The seed covers every key dispatched by
    network_toolbox_view, so this fallback should never fire for an API tool 
    if you add a new API tool, seed it (or set its tier in admin) or it'll be
    treated as free.
    """
    tier = Tool.objects.filter(tool_key=tool_key).values_list("tier", flat=True).first()
    return tier or "local"
