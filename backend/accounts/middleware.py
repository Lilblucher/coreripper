from django.utils import timezone

from .models import AuthToken

LAST_SEEN_UPDATE_THROTTLE = timezone.timedelta(minutes=5)


class TokenAuthMiddleware:
    """Resolves `Authorization: Bearer <token>` into request.user, site-wide.

    Runs after AuthenticationMiddleware so it only needs to override
    request.user when a valid token is present  session-based requests
    (e.g. the Django admin) are untouched. Every view in every app that
    checks request.user.is_authenticated / request.user.is_staff (blog,
    core's premium_required, etc.) works the same regardless of whether the
    caller used a session cookie or a bearer token.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            key = header.removeprefix("Bearer ").strip()
            token = AuthToken.objects.select_related("user").filter(key=key).first()
            if token and token.user.is_active and not token.is_expired:
                request.user = token.user
                request._auth_token = token
                # Powers the "last active" column on settings.html's Active
                # Sessions list. Throttled to avoid a write on every single
                # request  staleness up to 5 minutes is fine for that UI.
                now = timezone.now()
                if now - token.last_seen_at > LAST_SEEN_UPDATE_THROTTLE:
                    token.last_seen_at = now
                    token.save(update_fields=["last_seen_at"])
        return self.get_response(request)
