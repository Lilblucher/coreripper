"""Payment endpoints. Everything under /api/payments/ is covered by the
'payments' feature flag (core/middleware.py)  flipping it off is a real kill
switch for the whole flow, webhook included; any payment confirmed while the
flag was off is settled later by the verify poller, so nothing is lost.

Security model:
- The client only ever sends a price_id  the amount charged is resolved
  server-side from payments.models.PlanPrice. No client input decides cost.
- Settlement (pending→paid + Premium activation + receipt) happens only in
  accounts.subscription_utils.settle_payment, which is idempotent under races.
- The webhook never trusts its payload: the provider re-verifies against the
  gateway API, and the URL carries a secret compared with hmac.compare_digest.
"""
import hmac
import json
import re
from functools import wraps

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts.models import Payment
from accounts.subscription_utils import mark_payment_failed, settle_payment

from . import fx, get_provider
from .base import PaymentGatewayError, PaymentNotConfigured, PaymentNotSupported
from .models import CreditPackPrice, PlanPrice

VALID_METHODS = {"mtn_momo", "airtel_money", "card"}
MOMO_METHODS = {"mtn_momo", "airtel_money"}
# Mobile money is inherently Zambian → always ZMW. Card customers choose:
# Zambians pay the live-rate Kwacha equivalent, international customers pay USD.
VALID_CURRENCIES = {"ZMW", "USD"}

# Zambian mobile numbers: optional +260/260/0 prefix, then MTN (96/76),
# Airtel (95/75/97/77)  kept permissive across operator ranges; the operator
# actually used is the method the user picked, not the prefix.
ZAMBIA_PHONE_RE = re.compile(r"^(?:\+?260|0)?(9[567]|7[567])\d{7}$")

# Per-user creation throttle: a real person picks a plan and approves on their
# phone; nobody legitimately starts more charges than this.
CHARGE_RATE_LIMIT = 5
CHARGE_RATE_WINDOW_SECONDS = 600


def _login_required_json(view):
    """Like django.contrib.auth.decorators.login_required, but returns 401 JSON instead
    of redirecting to a login page  this is a JSON API, matching core.premium_required.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "login_required"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


def _parse_json_body(request):
    try:
        return json.loads(request.body or b"{}"), None
    except (ValueError, UnicodeDecodeError):
        return None, JsonResponse({"error": "invalid_json"}, status=400)


def _charge_rate_limited(user):
    key = f"chargerl:{user.id}"
    count = cache.get(key, 0)
    if count >= CHARGE_RATE_LIMIT:
        return True
    # Same simple cache pattern as accounts/trial.py: the window restarts on
    # each attempt while under the cap  fine for an abuse brake.
    cache.set(key, count + 1, CHARGE_RATE_WINDOW_SECONDS)
    return False


def _price_json(price, rate_info):
    return {
        "id": price.id,
        "label": price.label,
        "plan": price.plan,
        "display_amount_usd": str(price.display_amount_usd),
        # Computed from the real-time USD→ZMW market rate  not stored anywhere.
        "amount_zmw": str(fx.zmw_amount(price.display_amount_usd, fx=rate_info)),
        "period_days": price.period_days,
    }


def _pack_json(pack, rate_info):
    return {
        "id": pack.id,
        "label": pack.label,
        "credits": pack.credits,
        "display_amount_usd": str(pack.display_amount_usd),
        "amount_zmw": str(fx.zmw_amount(pack.display_amount_usd, fx=rate_info)),
    }


@require_GET
def pricing_view(request):
    """Public: the active price options (subscription plans + one-time credit
    packs), exactly as the admin configured them (USD), plus the live-rate
    Kwacha equivalent. This is the single source the pricing page, billing
    page, and charge flow all read from  an admin edit or a rate movement
    reflects everywhere at once."""
    from credits.services import claude_enabled

    options = PlanPrice.objects.filter(is_active=True)
    packs = CreditPackPrice.objects.filter(is_active=True)
    rate_info = fx.get_usd_to_zmw()
    return JsonResponse(
        {
            "options": [_price_json(p, rate_info) for p in options],
            "packs": [_pack_json(p, rate_info) for p in packs],
            # Packs are still listed while Sonnet-5 is switched off so the pricing
            # page can show what's coming, but they are not buyable  selling
            # credits for a model that can't run would be selling nothing.
            # create_charge_view enforces the same rule server-side.
            "packs_available": claude_enabled(),
            "fx": fx.fx_json(rate_info),
        }
    )


@require_GET
def payments_config_view(request):
    """Public: what the frontend needs to know about the gateway. Only ever the
    PUBLIC key  the secret key is never serialized anywhere."""
    import os

    from django.conf import settings

    provider = os.environ.get("PAYMENT_PROVIDER", "stub").lower()
    public_key = (os.environ.get("LENCO_PUBLIC_KEY") or "").strip()
    from .lenco import DEFAULT_WIDGET_URL

    return JsonResponse(
        {
            "provider": provider,
            # Kill switch: cards stay wired but hidden until PAYMENTS_CARD_ENABLED
            # is set (mobile money only for now  user decision).
            "card_available": (
                getattr(settings, "PAYMENTS_CARD_ENABLED", False)
                and provider == "lenco"
                and bool(public_key)
            ),
            "public_key": public_key or None,
            "widget_url": os.environ.get("LENCO_WIDGET_URL") or DEFAULT_WIDGET_URL,
        }
    )


@csrf_exempt
@require_POST
@_login_required_json
def create_charge_view(request):
    """POST {price_id | pack_id, method, phone?} → start a charge for an
    ACTIVE PlanPrice (subscription) or CreditPackPrice (one-time credit pack).

    The client never sends an amount. With PAYMENT_PROVIDER=stub this still
    creates a real pending Payment row and returns the manual-confirmation
    prompt; with lenco it triggers the USSD push / returns card widget params.
    """
    body, error = _parse_json_body(request)
    if error:
        return error

    from accounts.entitlements import monetization_enabled

    if not monetization_enabled():
        # Open-source mode: every account already has full access for free,
        # and the frontend checkout UI is hidden  this is defense-in-depth
        # for a direct API call, mirroring the claude_disabled pattern below.
        return JsonResponse(
            {
                "error": "monetization_disabled",
                "message": "CoreRipper is running in open-source mode right now  every account "
                "already has full access for free. Payments will return once they're funded.",
            },
            status=503,
        )

    if _charge_rate_limited(request.user):
        return JsonResponse(
            {"error": "rate_limited", "message": "Too many payment attempts. Please wait a few minutes and try again."},
            status=429,
        )

    price = pack = None
    if body.get("pack_id") is not None and body.get("price_id") is not None:
        return JsonResponse(
            {"error": "invalid_price", "message": "Send either price_id or pack_id, not both."}, status=400
        )
    if body.get("pack_id") is not None:
        try:
            pack = CreditPackPrice.objects.get(pk=int(body.get("pack_id")), is_active=True)
        except (CreditPackPrice.DoesNotExist, TypeError, ValueError):
            return JsonResponse(
                {"error": "invalid_price", "message": "That credit pack is not available."}, status=400
            )
        from credits.services import CLAUDE_DISABLED_MESSAGE, claude_enabled

        if not claude_enabled():
            # Credits only buy Sonnet-5, so while it's off a pack purchase would
            # take real money for something unusable. Subscriptions are unaffected
            # (their non-AI tier benefits are all live), hence the pack-only gate.
            return JsonResponse(
                {"error": "claude_disabled", "feature": "claude_ai", "message": CLAUDE_DISABLED_MESSAGE},
                status=503,
            )
    else:
        try:
            price = PlanPrice.objects.get(pk=int(body.get("price_id")), is_active=True)
        except (PlanPrice.DoesNotExist, TypeError, ValueError):
            return JsonResponse(
                {"error": "invalid_price", "message": "That price option is not available."}, status=400
            )

    method = (body.get("method") or "").strip()
    if method not in VALID_METHODS:
        return JsonResponse(
            {"error": "invalid_method", "message": f"'method' must be one of {sorted(VALID_METHODS)}."},
            status=400,
        )

    # Currency: the client only picks WHICH of the two supported currencies 
    # never the amount. Mobile money is Zambia-only, so it's always ZMW.
    if method in MOMO_METHODS:
        currency = "ZMW"
    else:
        currency = (body.get("currency") or "ZMW").strip().upper()
        if currency not in VALID_CURRENCIES:
            return JsonResponse(
                {"error": "invalid_currency", "message": "'currency' must be ZMW or USD."}, status=400
            )

    phone = (body.get("phone") or "").strip()
    if method in MOMO_METHODS:
        if not phone:
            return JsonResponse(
                {"error": "missing_field", "message": "'phone' is required for mobile money."}, status=400
            )
        if not ZAMBIA_PHONE_RE.match(phone.replace(" ", "")):
            return JsonResponse(
                {"error": "invalid_phone", "message": "Enter a valid Zambian mobile number (e.g. 0961234567)."},
                status=400,
            )

    try:
        result = get_provider().create_charge(
            user=request.user, price=price, currency=currency, phone=phone, method=method, pack=pack
        )
    except PaymentNotConfigured:
        return JsonResponse(
            {
                "error": "gateway_not_configured",
                "message": "Payments aren't live yet  the gateway is awaiting activation. Please try again later.",
            },
            status=503,
        )
    except PaymentGatewayError:
        return JsonResponse(
            {"error": "gateway_error", "message": "The payment gateway is having trouble. Please try again shortly."},
            status=502,
        )
    return JsonResponse(result)


@require_GET
@_login_required_json
def verify_charge_view(request, ref):
    """GET → current status of one of YOUR charges. On a verified 'paid' this
    settles the payment (activates Premium + emails the receipt)  polling
    alone is a complete activation path; the webhook is just an accelerant."""
    payment = Payment.objects.filter(user=request.user, provider_ref=ref).first()
    if payment is None:
        return JsonResponse({"error": "not_found"}, status=404)

    if payment.status in ("paid", "failed"):
        return JsonResponse({"ref": ref, "status": payment.status})

    status = get_provider().verify(ref)
    if status == "paid":
        settle_payment(payment.pk)
    elif status == "failed":
        mark_payment_failed(payment.pk)
    return JsonResponse({"ref": ref, "status": status})


@csrf_exempt
@require_POST
@_login_required_json
def submit_otp_view(request):
    """POST {ref, otp} → submit an operator OTP for one of YOUR pending charges."""
    body, error = _parse_json_body(request)
    if error:
        return error

    ref = (body.get("ref") or "").strip()
    otp = (body.get("otp") or "").strip()
    if not re.fullmatch(r"\d{4,8}", otp):
        return JsonResponse({"error": "invalid_otp", "message": "Enter the numeric code sent to your phone."}, status=400)

    payment = Payment.objects.filter(user=request.user, provider_ref=ref).first()
    if payment is None:
        return JsonResponse({"error": "not_found"}, status=404)
    if payment.status != "pending":
        return JsonResponse({"ref": ref, "status": payment.status})

    try:
        status = get_provider().submit_otp(ref, otp)
    except PaymentNotSupported:
        return JsonResponse({"error": "otp_not_supported"}, status=400)
    except PaymentNotConfigured:
        return JsonResponse({"error": "gateway_not_configured"}, status=503)
    except PaymentGatewayError:
        return JsonResponse({"error": "gateway_error", "message": "Couldn't submit the code. Please try again."}, status=502)

    if status == "paid":
        settle_payment(payment.pk)
    elif status == "failed":
        mark_payment_failed(payment.pk)
    return JsonResponse({"ref": ref, "status": status})


@csrf_exempt
@require_POST
def lenco_webhook_view(request, secret):
    """Unauthenticated inbound webhook from Lenco  defended in depth:
    1. Disabled entirely (404) until LENCO_WEBHOOK_SECRET is set.
    2. The URL path carries that secret, compared constant-time.
    3. The payload is only a hint: the provider re-verifies the reference
       against the Lenco API before any status is trusted.
    Always answers 200 for recognized-secret calls so Lenco doesn't retry-storm.
    """
    import os

    expected = (os.environ.get("LENCO_WEBHOOK_SECRET") or "").strip()
    if not expected:
        return JsonResponse({"error": "not_found"}, status=404)
    if not hmac.compare_digest(secret, expected):
        return JsonResponse({"error": "forbidden"}, status=403)

    try:
        result = get_provider().handle_webhook(request)
    except (PaymentNotConfigured, PaymentGatewayError):
        # Report received-but-unprocessed; the verify poller will settle it.
        return JsonResponse({"ok": True, "processed": False})

    ref = result.get("ref")
    payment = Payment.objects.filter(provider_ref=ref).first() if ref else None
    if payment is None:
        return JsonResponse({"ok": True, "ignored": True})

    status = result.get("status")
    if status == "paid":
        settle_payment(payment.pk)
    elif status == "failed":
        mark_payment_failed(payment.pk)
    return JsonResponse({"ok": True, "ref": ref, "status": status})
