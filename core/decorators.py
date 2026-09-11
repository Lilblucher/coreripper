from functools import wraps

from django.http import JsonResponse


def login_required_json(view):
    """Gate a view behind a logged-in user (any plan, incl. free).

    Used by the Livia AI tool endpoints  the pricing page promises Livia AI to
    every tier, so the endpoint itself is not premium-gated. Free users hit the
    $-spend quota (core.quota) on Livia and the empty credit wallet on Sonnet-5,
    both of which return their own honest errors.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "login_required", "upgrade_url": "/login.html"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


def premium_required(view):
    """Gate a view behind an active Premium subscription.

    Free-tool views/pages never carry this decorator  only premium and
    hybrid-premium endpoints do (see the implementation spec, section 4).

    Reads through accounts.entitlements.is_premium_effective rather than the
    raw Subscription.is_premium, so this gate is lifted for every logged-in
    account while the site is in open-source mode (the `monetization` feature
    flag is off) - see accounts/entitlements.py for the full mechanics.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "login_required", "upgrade_url": "/pricing/"}, status=401)
        from accounts.entitlements import is_premium_effective

        if not is_premium_effective(request.user):
            return JsonResponse({"error": "premium_required", "upgrade_url": "/pricing/"}, status=402)
        return view(request, *args, **kwargs)

    return wrapper
