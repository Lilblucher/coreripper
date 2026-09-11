from functools import wraps

from django.http import JsonResponse


def login_required_json(view):
    """Like django.contrib.auth.decorators.login_required, but returns 401 JSON
    instead of redirecting  this is a JSON API, not a template-rendered site."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "login_required"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


def is_admin(user):
    """A user counts as an admin if they're staff OR a superuser  a
    superuser is trivially an admin and shouldn't also need is_staff set."""
    return user.is_staff or user.is_superuser


def staff_required(view):
    """Gate a view behind an admin account  see is_admin(). There's no
    separate admin login or token, an admin logs in exactly like any other
    user and gets access based on their account."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "login_required"}, status=401)
        if not is_admin(request.user):
            return JsonResponse({"error": "staff_required"}, status=403)
        return view(request, *args, **kwargs)

    return wrapper


def superuser_required(view):
    """Gate a view behind a superuser account. Staff accounts exist only to
    write blog posts  everything else in the admin surface (user management,
    subscriptions, transactions, feature switches) is superuser-only."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "login_required"}, status=401)
        if not request.user.is_superuser:
            return JsonResponse({"error": "superuser_required"}, status=403)
        return view(request, *args, **kwargs)

    return wrapper
