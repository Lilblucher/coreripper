import json
import re
import secrets
from datetime import timedelta
import requests as pyrequests

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.mail import EmailMessage, send_mail
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .decorators import is_admin, login_required_json
from .entitlements import entitlements_json
from .models import (
    AuthToken,
    EmailVerificationToken,
    NotificationPreference,
    PasswordResetToken,
    Payment,
    Profile,
    RefreshToken,
    SupportTicket,
    SupportTicketAttachment,
    UsageLog,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESET_TOKEN_LIFETIME = timedelta(minutes=15)
RESET_REQUEST_COOLDOWN_SECONDS = 60
RESET_MAX_ATTEMPTS = 5
# Email verification reuses the same OTP semantics as password reset.
VERIFICATION_TOKEN_LIFETIME = RESET_TOKEN_LIFETIME
VERIFICATION_COOLDOWN_SECONDS = 60



def _warm_google_certs():
    """Pre-fetch Google's public certs into Django's cache so verify_oauth2_token
    doesn't make a cold outbound request during the gunicorn worker timeout window."""
    CACHE_KEY = "google_oauth2_certs_warm"
    if cache.get(CACHE_KEY):
        return
    try:
        pyrequests.get(
            "https://www.googleapis.com/oauth2/v1/certs",
            timeout=5,
        )
        cache.set(CACHE_KEY, True, timeout=3300)  # ~55 min, certs rotate hourly
    except Exception:
        pass  # silently skip; verify_oauth2_token will try itself


def _send_verification_code(user):
    """Invalidate any prior unused codes, issue a fresh 6-digit code, and email
    it (console backend prints it when SMTP isn't configured). Same shape as
    forgot_password_view's send. Returns the token row."""
    EmailVerificationToken.objects.filter(user=user, used=False).update(used=True)
    token = EmailVerificationToken.objects.create(user=user)
    send_mail(
        subject=f"{token.token} is your CoreRipper verification code",
        message=(
            "Welcome to CoreRipper. Enter this code to finish setting up your "
            "account:\n\n"
            f"    {token.token}\n\n"
            "The code expires in 15 minutes and can only be used once.\n\n"
            "If you didn't create a CoreRipper account, you can ignore this email "
            "- no account will be activated without this code.\n\n"
            "CoreRipper Security"
        ),
        from_email=settings.EMAIL_FROM_SECURITY,
        recipient_list=[user.email],
        fail_silently=False,
    )
    return token


def _send_welcome_email(user, trial_end=None):
    """Welcome a newly verified member.

    Sent at verification rather than at signup, because until then the address
    is unproven and the account has no trial - a welcome email to an unverified
    address is both undeliverable-in-principle and premature.

    Failure here must never break the verification response: the account is
    already live and the token already issued by the time this runs, so a mail
    outage would otherwise turn a successful signup into a 500.
    """
    from django.core.mail import EmailMessage

    trial_line = (
        f"Your 3-day Pro trial is running now and ends on {trial_end.strftime('%d %b %Y')}. "
        if trial_end
        else "Your 3-day Pro trial is running now. "
    )
    body = (
        f"Hello{' ' + user.first_name if user.first_name else ''},\n\n"
        "Welcome to CoreRipper, and thanks for joining.\n\n"
        f"{trial_line}It unlocks the full toolkit, so this is the best time to "
        "explore what's here:\n\n"
        f"  Workbench      Run many tools against one target at once, save the results\n"
        f"                 into projects, and export a client-ready report.\n"
        f"  Network tools  DNS, TLS, headers, blacklists, deliverability and a full\n"
        f"                 Security Grade scan for any domain you own.\n"
        f"  Monitoring     Watch a site or certificate on a schedule and get an email\n"
        f"                 the moment something changes.\n\n"
        "When the trial ends your account stays open on the Free plan - nothing is "
        "deleted and nothing is charged. You only pick a paid plan if you want to "
        "keep the premium tools.\n\n"
        "Everything lives at:  www.coreripper.site\n\n"
        "If you get stuck, reply to this email. A real person reads it.\n\n"
        "CoreRipper Support"
    )
    EmailMessage(
        subject="Welcome to CoreRipper",
        body=body,
        from_email=settings.EMAIL_FROM_SUPPORT,
        to=[user.email],
    ).send(fail_silently=False)


def _start_pro_trial(user):
    """Grant the 3-day pro-tier feature trial (zero Claude credits). Called at
    verification time, not signup, so the trial clock never burns while a user
    sits unverified."""
    now = timezone.now()
    end = now + timedelta(days=getattr(settings, "TRIAL_DAYS", 3))
    sub = user.subscription
    sub.plan = "pro"
    sub.status = "trialing"
    sub.renewal_state = "not_due"
    sub.current_period_start = now
    sub.current_period_end = end
    sub.expires_at = end
    sub.save(
        update_fields=[
            "plan",
            "status",
            "renewal_state",
            "current_period_start",
            "current_period_end",
            "expires_at",
            "updated_at",
        ]
    )


def _parse_json_body(request):
    try:
        return json.loads(request.body or b"{}"), None
    except (ValueError, UnicodeDecodeError):
        return None, JsonResponse({"error": "invalid_json"}, status=400)


def _parse_device_label(user_agent):
    """No UA-parsing library available on this box (offline pip)  a plain
    substring match covers the common cases well enough for a "which device
    is this" label, not a precise capability check."""
    ua = user_agent or ""
    if "iPhone" in ua:
        os_label = "iPhone"
    elif "iPad" in ua:
        os_label = "iPad"
    elif "Android" in ua:
        os_label = "Android"
    elif "Mac OS X" in ua:
        os_label = "macOS"
    elif "Windows" in ua:
        os_label = "Windows"
    elif "Linux" in ua:
        os_label = "Linux"
    else:
        os_label = "Unknown device"

    if "Edg/" in ua:
        browser = "Edge"
    elif "OPR/" in ua:
        browser = "Opera"
    elif "Chrome/" in ua:
        browser = "Chrome"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        browser = "Browser"

    return f"{browser} on {os_label}"


def _issue_token(user, request=None):
    """Always creates a NEW token  one per login/device, not one per user.
    That's the whole point of the 2026-07-16 AuthToken refactor (see the
    model docstring): settings.html's Active Sessions list needs a real row
    per device to show and revoke. Returns the AuthToken row (callers read
    .key); every new token gets an expiry  only "Remember Me" logins can
    outlive it, via the refresh flow (see refresh_view)."""
    device_label = ""
    ip_address = None
    if request is not None:
        device_label = _parse_device_label(request.META.get("HTTP_USER_AGENT", ""))
        ip_address = request.META.get("REMOTE_ADDR") or None
    return AuthToken.objects.create(
        user=user,
        device_label=device_label,
        ip_address=ip_address,
        expires_at=timezone.now() + timedelta(hours=settings.AUTH_TOKEN_LIFETIME_HOURS),
    )


def _session_json(user, token, remember_me=False, request=None):
    """The login/verify/google response shape: bearer token + its expiry +
    the user, plus a one-time-visible refresh token when Remember Me was
    ticked. Frontend stores all of it in localStorage; the swept
    CoreRipperAuth head snippet uses the expiry+refresh pair to renew."""
    payload = {
        "token": token.key,
        "token_expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "user": _user_json(user),
    }
    if remember_me:
        payload["refresh_token"] = RefreshToken.issue(user, token, request)
    return payload


def _unseen_alert_count(user):
    # Local import to avoid a startup-order dependency between accounts
    # (loaded early) and monitors (a later, optional Premium feature app).
    from monitors.models import AlertLog

    return AlertLog.objects.filter(monitor__user=user, seen_by_user=False).count()


def _user_json(user):
    from .entitlements import is_premium_effective

    sub = getattr(user, "subscription", None)
    profile = getattr(user, "profile", None)
    prefs = getattr(user, "notification_prefs", None)
    wallet = getattr(user, "credit_wallet", None)
    # Reads through is_premium_effective (not the raw Subscription.is_premium)
    # so every field below reports "premium" for any logged-in account while
    # the site is in open-source mode (the `monetization` flag is off).
    premium_effective = is_premium_effective(user)
    next_pack_expiry = None
    if wallet:
        soonest = (
            wallet.pack_lots.filter(credits_remaining__gt=0, expires_at__gt=timezone.now())
            .order_by("expires_at")
            .values_list("expires_at", flat=True)
            .first()
        )
        next_pack_expiry = soonest.isoformat() if soonest else None
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "is_admin": is_admin(user),
        "date_joined": user.date_joined.isoformat(),
        # Flat fields kept for backward compat (e.g. dashboard.html reads
        # is_premium directly)  subscription below is the richer, nested
        # form the nav's tier badge/trial banner read from.
        "plan": sub.plan if sub else "free",
        "is_premium": premium_effective,
        # What this user's plan actually includes  the frontend renders caps
        # from here instead of hardcoding per-plan numbers page by page.
        "entitlements": entitlements_json(user),
        "unseen_alert_count": _unseen_alert_count(user),
        "subscription": {
            "plan": sub.plan if sub else "free",
            # "active" kept for older frontend readers  now the computed shim.
            "active": premium_effective,
            "status": sub.status if sub else "expired",
            "renewal_state": sub.renewal_state if sub else "not_due",
            "cancel_at_period_end": sub.cancel_at_period_end if sub else False,
            "current_period_end": sub.current_period_end.isoformat() if sub and sub.current_period_end else None,
            "expires_at": sub.expires_at.isoformat() if sub and sub.expires_at else None,
            "is_premium": premium_effective,
            "is_trial": sub.is_trial if sub else False,
            "trial_days_remaining": sub.trial_days_remaining if sub else None,
        },
        "credits": {
            "subscription": wallet.subscription_balance if wallet else 0,
            "pack": wallet.pack_balance if wallet else 0,
            "total": wallet.total_balance if wallet else 0,
            "next_pack_expiry": next_pack_expiry,
        },
        "profile": {
            "company": profile.company if profile else "",
            "title": profile.title if profile else "",
            "phone_dial_code": profile.phone_dial_code if profile else "",
            "phone_national": profile.phone_national if profile else "",
            "timezone": profile.timezone if profile else "UTC+0",
            "preferred_model": profile.preferred_model if profile else "groq",
            "email_verified": profile.email_verified if profile else False,
        },
        "notification_prefs": {
            "email_alerts": prefs.email_alerts if prefs else True,
            "whatsapp_alerts": prefs.whatsapp_alerts if prefs else True,
            "weekly_digest": prefs.weekly_digest if prefs else False,
            "product_updates": prefs.product_updates if prefs else True,
        },
    }


@csrf_exempt
@require_http_methods(["POST"])
def signup_view(request):
    """Every account  customer or admin  is created the same way. There's
    no separate admin signup; an account only becomes an admin if someone
    with Django admin/shell access sets is_staff=True on it afterwards."""
    body, error = _parse_json_body(request)
    if error:
        return error

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not EMAIL_RE.match(email):
        return JsonResponse({"error": "invalid_email"}, status=400)
    if len(password) < 8:
        return JsonResponse({"error": "weak_password", "message": "Password must be at least 8 characters."}, status=400)
    if User.objects.filter(username=email).exists():
        return JsonResponse({"error": "email_taken"}, status=409)

    user = User.objects.create_user(username=email, email=email, password=password)
    # No token and no trial yet  the account is inert until the emailed 6-digit
    # code is verified (see verify_email_view), which is when the 3-day pro trial
    # starts. subscription/profile/wallet are auto-created by post_save signals.
    try:
        _send_verification_code(user)
    except Exception as exc:
        # Leave the account in place  the user can request a resend rather than
        # re-signing-up. Surface a clear error so the frontend can offer resend.
        print(f"[signup_view] failed to send verification code to {email}: {exc}")
        return JsonResponse(
            {
                "error": "email_send_failed",
                "message": "Couldn't send the verification email. Please try resending.",
                "email": email,
            },
            status=502,
        )
    return JsonResponse({"verification_required": True, "email": email}, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def verify_email_view(request):
    """Verify the signup code (same validation ladder as reset_password_view).
    On success: mark verified, start the 3-day pro trial, issue a token,
    return {token, user} — the same shape signup used to."""
    body, error = _parse_json_body(request)
    if error:
        return error

    email = (body.get("email") or "").strip().lower()
    code = (body.get("code") or "").strip().upper()           # ← FIX 1: normalise to uppercase

    user = User.objects.filter(username=email).first()
    profile = getattr(user, "profile", None) if user else None

    token = (
        EmailVerificationToken.objects.filter(user=user, used=False).order_by("-created_at").first()
        if user is not None
        else None
    )

    # ← FIX 2: check already_verified AFTER fetching the token (order matters
    #   because a verified user has no unused token; the old order left token=None
    #   and then crashed on token.attempts below).
    if profile and profile.email_verified:
        return JsonResponse({"error": "already_verified", "message": "This email is already verified."}, status=400)

    # ← FIX 3: expiry is checked BEFORE the code match so a timed-out
    #   submission doesn't burn an attempt — the token is dead regardless.
    if token is not None and timezone.now() - token.created_at > VERIFICATION_TOKEN_LIFETIME:
        token.used = True
        token.save(update_fields=["used"])
        return JsonResponse({"error": "expired_code", "message": "This code has expired. Request a new one."}, status=400)

    if token is None or token.token != code:
        if token is not None:
            token.attempts += 1
            if token.attempts >= RESET_MAX_ATTEMPTS:
                token.used = True  # burn it — force requesting a fresh code
            token.save(update_fields=["attempts", "used"])
        return JsonResponse({"error": "invalid_code", "message": "Incorrect or expired code."}, status=400)

    token.used = True
    token.save(update_fields=["used"])
    if profile:
        profile.email_verified = True
        profile.save(update_fields=["email_verified", "updated_at"])
    _start_pro_trial(user)
    try:
        _send_welcome_email(user, trial_end=user.subscription.current_period_end)
    except Exception as exc:
        print(f"[verify_email_view] welcome email failed for {user.email}: {exc}")
    issued = _issue_token(user, request)
    return JsonResponse(_session_json(user, issued, bool(body.get("remember_me")), request), status=200)


@csrf_exempt
@require_http_methods(["POST"])
def resend_verification_view(request):
    """Re-send a signup verification code (cooldown-guarded). No-op message if
    already verified."""
    body, error = _parse_json_body(request)
    if error:
        return error

    email = (body.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        return JsonResponse({"error": "invalid_email"}, status=400)

    user = User.objects.filter(username=email).first()
    if user is None:
        return JsonResponse({"error": "email_not_found", "message": "No account found with that email."}, status=404)

    profile = getattr(user, "profile", None)
    if profile and profile.email_verified:
        return JsonResponse({"message": "This email is already verified. You can log in."})

    cooldown_key = f"email-verification-cooldown:{email}"
    if cache.get(cooldown_key):
        return JsonResponse(
            {"error": "cooldown", "message": "A code was sent recently. Check your email or wait a minute."},
            status=429,
        )
    cache.set(cooldown_key, True, VERIFICATION_COOLDOWN_SECONDS)

    try:
        _send_verification_code(user)
    except Exception as exc:
        print(f"[resend_verification_view] failed to send code to {email}: {exc}")
        return JsonResponse({"error": "email_send_failed", "message": "Couldn't send the email. Try again later."}, status=502)
    return JsonResponse({"message": "A new verification code has been sent to your email."})


@csrf_exempt
@require_http_methods(["POST"])
def login_view(request):
    """The one login endpoint for everyone. Admin accounts log in here exactly
    like customer accounts  access to the admin panel is decided afterwards
    by checking is_staff on the account, not by a separate login flow."""
    body, error = _parse_json_body(request)
    if error:
        return error

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    user = authenticate(username=email, password=password)
    if user is None:
        return JsonResponse({"error": "invalid_credentials"}, status=401)

    # Correct password but unverified email → block token issue and steer the
    # frontend to the code-entry step (a resend is triggered client-side).
    profile = getattr(user, "profile", None)
    if profile and not profile.email_verified:
        return JsonResponse(
            {
                "error": "email_unverified",
                "message": "Please verify your email to finish signing in.",
                "email": email,
            },
            status=403,
        )

    token = _issue_token(user, request)
    return JsonResponse(_session_json(user, token, bool(body.get("remember_me")), request))


@require_GET
@login_required_json
def me_view(request):
    return JsonResponse(_user_json(request.user))


@csrf_exempt
@require_http_methods(["POST"])
def forgot_password_view(request):
    """Explicitly confirms whether `email` is registered before sending
    anything (product decision  trades away the usual "generic response"
    anti-enumeration protection for a clearer UX). If it is, a 6-digit reset
    code is emailed (or printed to the console if EMAIL/PASSKEY aren't
    configured yet  see core_backend.settings)."""
    body, error = _parse_json_body(request)
    if error:
        return error

    email = (body.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        return JsonResponse({"error": "invalid_email"}, status=400)

    user = User.objects.filter(username=email).first()
    if user is None:
        return JsonResponse({"error": "email_not_found", "message": "No account found with that email."}, status=404)

    cooldown_key = f"password-reset-cooldown:{email}"
    if cache.get(cooldown_key):
        return JsonResponse(
            {"error": "cooldown", "message": "A code was already sent recently. Check your email, or wait a minute before requesting another."},
            status=429,
        )
    cache.set(cooldown_key, True, RESET_REQUEST_COOLDOWN_SECONDS)

    # Only the most recently issued code should be valid at any given time.
    PasswordResetToken.objects.filter(user=user, used=False).update(used=True)
    reset_token = PasswordResetToken.objects.create(user=user)

    try:
        send_mail(
            subject=f"{reset_token.token} is your CoreRipper password reset code",
            message=(
                "We received a request to reset the password on your CoreRipper "
                "account. Enter this code to choose a new one:\n\n"
                f"    {reset_token.token}\n\n"
                "The code expires in 15 minutes and can only be used once.\n\n"
                "If you didn't request this, you can ignore this email - your "
                "password will not change, and no one can reset it without this "
                "code. If you get these unexpectedly and often, reply to this "
                "email and we'll look into it.\n\n"
                "CoreRipper Security"
            ),
            from_email=settings.EMAIL_FROM_SECURITY,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as exc:
        print(f"[forgot_password_view] failed to send reset code to {email}: {exc}")
        return JsonResponse({"error": "email_send_failed", "message": "Couldn't send the reset email. Please try again later."}, status=502)

    return JsonResponse({"message": "A reset code has been sent to your email."})


@csrf_exempt
@require_http_methods(["POST"])
def reset_password_view(request):
    body, error = _parse_json_body(request)
    if error:
        return error

    email = (body.get("email") or "").strip().lower()
    code = (body.get("code") or "").strip()
    new_password = body.get("new_password") or ""

    if len(new_password) < 8:
        return JsonResponse({"error": "weak_password", "message": "Password must be at least 8 characters."}, status=400)

    user = User.objects.filter(username=email).first()
    reset_token = (
        PasswordResetToken.objects.filter(user=user, used=False).order_by("-created_at").first()
        if user is not None
        else None
    )

    if reset_token is None or reset_token.token != code:
        if reset_token is not None:
            reset_token.attempts += 1
            if reset_token.attempts >= RESET_MAX_ATTEMPTS:
                reset_token.used = True  # burn it  force requesting a fresh code
            reset_token.save(update_fields=["attempts", "used"])
        return JsonResponse({"error": "invalid_code", "message": "Incorrect or expired code."}, status=400)

    if timezone.now() - reset_token.created_at > RESET_TOKEN_LIFETIME:
        reset_token.used = True
        reset_token.save(update_fields=["used"])
        return JsonResponse({"error": "expired_code", "message": "This code has expired. Request a new one."}, status=400)

    user.set_password(new_password)
    user.save(update_fields=["password"])

    reset_token.used = True
    reset_token.save(update_fields=["used"])
    # A password reset should log out any existing sessions.
    AuthToken.objects.filter(user=user).delete()

    return JsonResponse({"message": "Password reset successfully. You can now log in."})


@csrf_exempt
@require_http_methods(["PATCH"])
@login_required_json
def profile_view(request):
    """Saves first/last name (native User fields) + the extra Profile fields
    (company, title, phone, timezone). Real persistence  settings.html's
    profile section reads/writes this, not a fake 'saved' toast."""
    body, error = _parse_json_body(request)
    if error:
        return error

    if body.get("preferred_model") == "claude":
        # Validated before anything is written, so a rejected model choice can't
        # silently drop the other fields in the same PATCH. Don't persist a
        # preference for a switched-off model  it would sit in the DB looking
        # selected while every call fell back to Livia.
        from credits.services import CLAUDE_DISABLED_MESSAGE, claude_enabled

        if not claude_enabled():
            return JsonResponse(
                {"error": "claude_disabled", "feature": "claude_ai", "message": CLAUDE_DISABLED_MESSAGE},
                status=503,
            )

    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    if "first_name" in body:
        user.first_name = (body.get("first_name") or "").strip()[:150]
    if "last_name" in body:
        user.last_name = (body.get("last_name") or "").strip()[:150]
    user.save(update_fields=["first_name", "last_name"])

    for field in ("company", "title", "phone_dial_code", "phone_national", "timezone"):
        if field in body:
            setattr(profile, field, (body.get(field) or "").strip()[:120])

    if "preferred_model" in body:
        model = body.get("preferred_model")
        if model in dict(Profile.MODEL_CHOICES):
            profile.preferred_model = model

    profile.save()

    return JsonResponse(_user_json(user))


@csrf_exempt
@require_http_methods(["PATCH"])
@login_required_json
def notifications_view(request):
    """email_alerts/whatsapp_alerts are real gates checked by
    monitors.tasks.send_email_alert/send_whatsapp_alert (see there for the
    enforcement side)  not cosmetic toggles. weekly_digest is consumed by
    the weekly account-activity digest; product_updates is consumed by the
    newsletter (accounts.tasks.send_newsletter, Fri 09:00 UTC)  both real
    Celery beat tasks, not cosmetic toggles."""
    body, error = _parse_json_body(request)
    if error:
        return error

    prefs, _ = NotificationPreference.objects.get_or_create(user=request.user)
    for field in ("email_alerts", "whatsapp_alerts", "weekly_digest", "product_updates"):
        if field in body:
            setattr(prefs, field, bool(body.get(field)))
    prefs.save()

    return JsonResponse(_user_json(request.user)["notification_prefs"])


@csrf_exempt
@require_http_methods(["POST"])
@login_required_json
def change_password_view(request):
    body, error = _parse_json_body(request)
    if error:
        return error

    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""

    if authenticate(username=request.user.username, password=current_password) is None:
        return JsonResponse({"error": "invalid_current_password", "message": "Current password is incorrect."}, status=400)
    if len(new_password) < 8:
        return JsonResponse({"error": "weak_password", "message": "Password must be at least 8 characters."}, status=400)

    request.user.set_password(new_password)
    request.user.save(update_fields=["password"])

    # Changing a password is a "something might be compromised" signal 
    # kill every session on every device, not just this one, then hand back
    # a fresh token immediately so this request's own session isn't logged
    # out by its own success.
    AuthToken.objects.filter(user=request.user).delete()
    new_token = _issue_token(request.user, request)

    # No refresh token on the replacement session  after a compromise signal,
    # long-lived credentials should be re-earned by a fresh Remember-Me login.
    return JsonResponse(
        {
            "message": "Password updated.",
            "token": new_token.key,
            "token_expires_at": new_token.expires_at.isoformat(),
        }
    )


@require_GET
@login_required_json
def billing_view(request):
    """Real usage/plan/invoice data for billing.html  no mocked numbers.
    Note the AI-usage cap shown here is the real dollar budget
    (core.quota.PREMIUM_MONTHLY_CAP_USD), not a fake call-count limit  this
    project doesn't enforce a call-count cap anywhere, only a spend cap, so
    showing a count-based cap would misrepresent what's actually enforced.
    """
    from monitors.models import Monitor

    from core.quota import PREMIUM_MONTHLY_CAP_USD, user_month_spend
    from credits.models import CreditWallet

    from .entitlements import entitlement, get_plan

    user = request.user
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    ai_calls_this_month = UsageLog.objects.filter(user=user, created_at__gte=month_start).count()
    spend_this_month = user_month_spend(user)
    monitors_active = Monitor.objects.filter(user=user, is_active=True).count()

    # Claude-credit wallet  the real customer-facing AI usage metric (the $
    # spend above is only an internal free-model margin guardrail). Grant is the
    # plan's monthly allowance; balance is what's left this cycle.
    wallet, _ = CreditWallet.objects.get_or_create(user=user)
    plan = get_plan(user)  # normalized tier (expired sub reads "free")
    monthly_grant = settings.TIER_MONTHLY_CREDITS.get(plan, 0)

    from core.pdf import invoice_number

    invoices = [
        {
            "id": p.id,
            "number": invoice_number(p),
            "amount": str(p.amount),
            "currency": p.currency,
            "status": p.status,
            "provider": p.provider,
            "label": (
                f"{p.credits_amount}-credit pack"
                if (p.pack_id or p.credits_amount)
                else (p.price.label if p.price else "Subscription")
            ),
            "created_at": p.created_at.isoformat(),
        }
        for p in Payment.objects.filter(user=user, status="paid")
        .select_related("price")
        .order_by("-created_at")[:12]
    ]

    return JsonResponse(
        {
            "subscription": _user_json(user)["subscription"],
            "ai_calls_this_month": ai_calls_this_month,
            "spend_this_month_usd": str(spend_this_month),
            "spend_cap_usd": str(PREMIUM_MONTHLY_CAP_USD),
            "monitors_active": monitors_active,
            # Per-plan cap, not a flat one  Free/Lite include no monitors.
            "monitors_cap": entitlement(user, "monitors"),
            "credits": {
                "subscription_balance": wallet.subscription_balance,
                "pack_balance": wallet.pack_balance,
                "total_balance": wallet.total_balance,
                "monthly_grant": monthly_grant,
            },
            "entitlements": entitlements_json(user),
            "invoices": invoices,
        }
    )


@require_http_methods(["GET"])
def invoice_pdf_view(request, payment_id):
    """Re-download the PDF invoice for one payment.

    Scoped to `request.user` and to settled payments only: an invoice for a
    pending charge would be a document asserting a payment that hasn't happened.
    Nothing is stored - the PDF is rebuilt from the Payment row's own frozen
    amount/currency snapshot on each request, so a reprint years later still
    shows what was actually charged (see the FX-snapshot rule in CLAUDE.md).
    """
    if not request.user.is_authenticated:
        return JsonResponse(
            {"error": "auth_required", "message": "Sign in to download an invoice."}, status=401
        )
    payment = Payment.objects.filter(id=payment_id, user=request.user, status="paid").first()
    if payment is None:
        return JsonResponse(
            {"error": "not_found", "message": "No paid invoice with that id on your account."},
            status=404,
        )

    from core.pdf import build_invoice_pdf, invoice_number

    ref = invoice_number(payment)
    response = HttpResponse(build_invoice_pdf(payment), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="CoreRipper-invoice-{ref}.pdf"'
    return response


MAX_TICKET_ATTACHMENTS = 5
MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10MB/file


@csrf_exempt
@require_http_methods(["POST"])
def support_ticket_view(request):
    """multipart/form-data: first_name, last_name, email, domain_or_ip,
    category, description, files[] (up to MAX_TICKET_ATTACHMENTS). Creates a
    real SupportTicket row with a real generated ticket ID  nothing here is
    faked client-side.

    Open to guests: no login required. Logged-in users have the ticket linked
    back to their account (SupportTicket.user); guests just leave that FK null
    and identify themselves via the email field on the ticket itself.
    """
    category = (request.POST.get("category") or "").strip()
    description = (request.POST.get("description") or "").strip()
    domain_or_ip = (request.POST.get("domain_or_ip") or "").strip()
    # Guests must supply an email; logged-in users default to their account email.
    default_email = request.user.email if request.user.is_authenticated else ""
    email = (request.POST.get("email") or default_email or "").strip()

    valid_categories = {c[0] for c in SupportTicket.CATEGORY_CHOICES}
    if category not in valid_categories:
        return JsonResponse({"error": "invalid_category", "message": f"'category' must be one of {sorted(valid_categories)}."}, status=400)
    if not description:
        return JsonResponse({"error": "missing_field", "message": "'description' is required."}, status=400)
    if len(description) > 2000:
        return JsonResponse({"error": "description_too_long", "message": "Description must be 2000 characters or fewer."}, status=400)
    if not domain_or_ip:
        return JsonResponse({"error": "missing_field", "message": "'domain_or_ip' is required."}, status=400)
    if not EMAIL_RE.match(email):
        return JsonResponse({"error": "invalid_email"}, status=400)

    files = request.FILES.getlist("files")
    if len(files) > MAX_TICKET_ATTACHMENTS:
        return JsonResponse({"error": "too_many_files", "message": f"Max {MAX_TICKET_ATTACHMENTS} attachments."}, status=400)
    for f in files:
        if f.size > MAX_ATTACHMENT_SIZE_BYTES:
            return JsonResponse({"error": "file_too_large", "message": f"'{f.name}' exceeds the 10MB limit."}, status=400)

    ticket = SupportTicket.objects.create(
        user=request.user if request.user.is_authenticated else None,
        first_name=(request.POST.get("first_name") or "").strip()[:80],
        last_name=(request.POST.get("last_name") or "").strip()[:80],
        email=email,
        domain_or_ip=domain_or_ip[:255],
        category=category,
        description=description,
    )
    stored_attachments = []
    for f in files:
        # Rewind so the same UploadedFile can be re-read for the outbound email
        # attachment below (Django rewinds after FileField.save, but we cache
        # bytes now to be certain and to avoid loading the saved file back from
        # disk).
        f.seek(0)
        blob = f.read()
        f.seek(0)
        SupportTicketAttachment.objects.create(ticket=ticket, file=f, original_name=f.name[:255])
        stored_attachments.append((f.name[:255], blob, f.content_type or "application/octet-stream"))

    submitter_name = " ".join(filter(None, [ticket.first_name, ticket.last_name])).strip() or "(no name)"
    account_line = (
        f"Account: {request.user.email} (id {request.user.id})"
        if request.user.is_authenticated
        else "Account: guest (not signed in)"
    )
    support_body = (
        f"New support ticket: {ticket.ticket_id}\n"
        f"{'=' * 40}\n\n"
        f"From: {submitter_name} <{email}>\n"
        f"{account_line}\n"
        f"Category: {ticket.get_category_display()}\n"
        f"Domain/IP: {ticket.domain_or_ip}\n"
        f"Attachments: {len(stored_attachments)}\n\n"
        f"{ticket.description}\n"
    )
    try:
        support_msg = EmailMessage(
            subject=f"[{ticket.ticket_id}] {ticket.get_category_display()}  {domain_or_ip}",
            body=support_body,
            from_email=settings.EMAIL_FROM_SUPPORT,
            to=[settings.SUPPORT_EMAIL],
            reply_to=[email],
        )
        for name, blob, ctype in stored_attachments:
            support_msg.attach(name, blob, ctype)
        support_msg.send(fail_silently=False)
    except Exception as exc:
        # Log but don't fail the request  the ticket row is the source of
        # truth, and the confirmation email below still tells the submitter
        # we've got it.
        print(f"[support_ticket_view] support inbox delivery failed for {ticket.ticket_id}: {exc}")

    try:
        send_mail(
            subject=f"[{ticket.ticket_id}] We've received your request",
            message=(
                f"Hello{' ' + ticket.first_name if ticket.first_name else ''},\n\n"
                "Thanks for getting in touch. Your request is logged and a member of "
                "the team will reply to this address.\n\n"
                f"Reference   {ticket.ticket_id}\n"
                f"Category    {ticket.get_category_display()}\n"
                f"Domain/IP   {ticket.domain_or_ip}\n\n"
                "What you told us:\n"
                f"{ticket.description}\n\n"
                "If you have anything to add, just reply to this email and keep the "
                "reference in the subject line so it stays on the same ticket.\n\n"
                "CoreRipper Support"
            ),
            from_email=settings.EMAIL_FROM_SUPPORT,
            recipient_list=[email],
            fail_silently=True,  # confirmation email is a nicety, not the point of this endpoint
        )
    except Exception as exc:
        print(f"[support_ticket_view] confirmation email failed for {ticket.ticket_id}: {exc}")

    return JsonResponse({"ticket_id": ticket.ticket_id}, status=201)


@require_GET
@login_required_json
def sessions_view(request):
    current_key = getattr(getattr(request, "_auth_token", None), "key", None)
    now = timezone.now()
    tokens = (
        AuthToken.objects.filter(user=request.user)
        # Expired sessions are dead, not revocable  hide them. Null expiry =
        # pre-migration row, still valid.
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .annotate(
            remembered=Exists(
                RefreshToken.objects.filter(auth_token=OuterRef("pk"), revoked=False, expires_at__gt=now)
            )
        )
        .order_by("-last_seen_at")
    )
    sessions = [
        {
            "id": t.id,
            "device_label": t.device_label or "Unknown device",
            "ip_address": t.ip_address,
            "created_at": t.created_at.isoformat(),
            "last_seen_at": t.last_seen_at.isoformat(),
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            # True = a live Remember-Me refresh token can renew this session
            "remembered": t.remembered,
            "is_current": t.key == current_key,
        }
        for t in tokens
    ]
    return JsonResponse({"sessions": sessions})


@csrf_exempt
@require_http_methods(["DELETE"])
@login_required_json
def revoke_session_view(request, session_id):
    """Scoped to request.user so one user can never revoke another's
    session  the id alone isn't enough, it must also belong to the caller.
    Revoking the CURRENT session is allowed (that's just "log out this
    device" from itself)  no special-casing needed."""
    deleted, _ = AuthToken.objects.filter(id=session_id, user=request.user).delete()
    if not deleted:
        return JsonResponse({"error": "not_found"}, status=404)
    return JsonResponse({"message": "Session revoked."})


@csrf_exempt
@require_http_methods(["POST"])
@login_required_json
def delete_account_view(request):
    """Irreversible. Requires the current password as re-authentication 
    not just a confirm dialog  since this is the one truly destructive
    endpoint in the whole project. Every FK to User across every app uses
    on_delete=CASCADE (verified before writing this), so user.delete() alone
    cleanly removes every related row: Subscription, Profile,
    NotificationPreference, UsageLog, Payment, every AuthToken (all
    devices), PasswordResetToken, Monitor (+ its AlertLogs via Monitor's own
    CASCADE), DashboardSection/DashboardProject/SavedResult, SupportTicket
    (+ attachments), SubnetDrillStreak."""
    body, error = _parse_json_body(request)
    if error:
        return error

    password = body.get("password") or ""
    if authenticate(username=request.user.username, password=password) is None:
        return JsonResponse({"error": "invalid_password", "message": "Incorrect password"}, status=400)
    try:
        _warm_google_certs()  # no-op if already cached
        idinfo = google_id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)
    except ValueError as e:
        import logging
        logging.getLogger("django.request").warning("Google token verification failed: %s", e)
        return JsonResponse({"error": "invalid_token", "message": "Google sign-in failed - please try again."}, status=400)
    except BaseException as e:  # catches SystemExit from gunicorn worker abort
        import logging
        logging.getLogger("django.request").exception("Google token verification error")
        return JsonReesponse({"error": "invalid_password", "message": "Incorrect password."}, status=400)

    email = request.user.email
    request.user.delete()
    print(f"[delete_account_view] account deleted: {email}")

    return JsonResponse({"message": "Account deleted."})


@csrf_exempt
def google_login_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, Exception):
        return JsonResponse({"error": "invalid_json"}, status=400)

    credential = (data.get("credential") or "").strip()
    if not credential:
        return JsonResponse({"error": "missing_credential"}, status=400)

    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "")
    if not client_id:
        return JsonResponse({"error": "google_not_configured", "message": "Google sign-in is not available right now."}, status=503)

    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
    except ImportError:
        import logging
        logging.getLogger("django.request").exception("google-auth package not installed")
        return JsonResponse({"error": "google_not_configured", "message": "Google sign-in is not available right now."}, status=503)

    try:
        _warm_google_certs()  # no-op if already cached
        idinfo = google_id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)
    except ValueError as e:
        import logging
        logging.getLogger("django.request").warning("Google token verification failed: %s", e)
        return JsonResponse({"error": "invalid_token", "message": "Google sign-in failed - please try again."}, status=400)
    except BaseException as e:  # catches SystemExit from gunicorn worker abort
        import logging
        logging.getLogger("django.request").exception("Google token verification error")
        return JsonResponse({"error": "google_verify_failed", "message": "Google sign-in failed please try again."}, status=500)

    email = (idinfo.get("email") or "").lower().strip()
    if not email:
        return JsonResponse({"error": "no_email"}, status=400)
    if not idinfo.get("email_verified"):
        return JsonResponse({"error": "email_not_verified"}, status=400)

    intent = data.get("intent", "login")
    already_exists = User.objects.filter(email=email).exists()
    if intent == "signup" and already_exists:
        return JsonResponse(
            {"error": "account_exists", "message": "An account with this email already exists - log in instead."},
            status=409,
        )

    try:
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": email,
                "first_name": idinfo.get("given_name", ""),
                "last_name": idinfo.get("family_name", ""),
                "is_active": True,
            },
        )
    except Exception:
        import logging
        logging.getLogger("django.request").exception("Google login: user create/get failed")
        return JsonResponse({"error": "server_error", "message": "Something went wrong - please try again."}, status=500)

    if not user.is_active:
        return JsonResponse({"error": "account_disabled"}, status=403)

    if created:
        profile = user.profile
        profile.email_verified = True
        profile.save(update_fields=["email_verified", "updated_at"])
        _start_pro_trial(user)
        try:
            _send_welcome_email(user, trial_end=user.subscription.current_period_end)
        except Exception:
            pass

    token = _issue_token(user, request)
    return JsonResponse(_session_json(user, token, bool(data.get("remember_me")), request))


@csrf_exempt
@require_http_methods(["POST"])
def refresh_view(request):
    """Trade a valid Remember-Me refresh token for a renewed session: the
    device's AuthToken row is kept (settings.html's session list stays
    stable) but its bearer key is rotated and its expiry pushed out, and the
    refresh token itself is single-use  the old row is revoked and a
    successor issued in the same transaction. A revoked or expired refresh
    token is a plain 401 (no chain-nuking: two tabs racing the same rotation
    is far likelier than a real replay, and the loser of that race must not
    log the whole device out)."""
    body, error = _parse_json_body(request)
    if error:
        return error

    raw = (body.get("refresh_token") or "").strip()
    if not raw:
        return JsonResponse({"error": "missing_refresh_token"}, status=400)

    now = timezone.now()
    with transaction.atomic():
        rt = (
            RefreshToken.objects.select_for_update()
            .select_related("auth_token", "user")
            .filter(token_hash=RefreshToken.hash_raw(raw))
            .first()
        )
        if rt is None or rt.revoked or rt.expires_at <= now or not rt.user.is_active:
            return JsonResponse({"error": "invalid_refresh_token"}, status=401)

        rt.revoked = True
        rt.last_used_at = now
        rt.save(update_fields=["revoked", "last_used_at"])

        auth_token = rt.auth_token
        auth_token.key = secrets.token_hex(32)
        auth_token.expires_at = now + timedelta(hours=settings.AUTH_TOKEN_LIFETIME_HOURS)
        auth_token.last_seen_at = now
        auth_token.save(update_fields=["key", "expires_at", "last_seen_at"])

        new_raw = RefreshToken.issue(rt.user, auth_token, request)

    return JsonResponse(
        {
            "token": auth_token.key,
            "token_expires_at": auth_token.expires_at.isoformat(),
            "refresh_token": new_raw,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def logout_view(request):
    """Server-side logout: delete this device's AuthToken (its refresh tokens
    CASCADE away with it). Deliberately not @login_required_json  the access
    token may already be expired, in which case the body's refresh token is
    what identifies the session to kill. Always 200: logout must never fail
    visibly."""
    token = getattr(request, "_auth_token", None)
    if token is not None:
        token.delete()
    else:
        body, _ = _parse_json_body(request)
        raw = ((body or {}).get("refresh_token") or "").strip()
        if raw:
            rt = RefreshToken.objects.select_related("auth_token").filter(
                token_hash=RefreshToken.hash_raw(raw)
            ).first()
            if rt is not None:
                rt.auth_token.delete()
    return JsonResponse({"message": "Logged out."})
