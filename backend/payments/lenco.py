"""LencoProvider  real payment adapter for the Lenco gateway (lenco.co).

Written OFFLINE from documented API knowledge: every URL, path, operator slug,
status string, and phone format lives in the constants block below so the first
live test can correct any of them in one place without touching logic.

FIRST LIVE TEST CHECKLIST (run this the day the API key arrives):
 1. In backend/.env set: PAYMENT_PROVIDER=lenco, LENCO_API_KEY=<secret key>,
    LENCO_PUBLIC_KEY=<public key>, LENCO_WEBHOOK_SECRET=<any long random string>.
    Restart the backend. Gotcha: load_dotenv() won't override a var already
    exported (even blank) in the shell  `echo $LENCO_API_KEY` first.
 2. Constants below were verified 2026-07-29 against the live Lenco API docs
    (lenco-api.readme.io) and two working client libraries: base URL + version,
    all three paths, operator slugs, the STATUS_MAP vocabulary, the numeric
    `amount` + `country` momo payload, and the international ("260...") phone
    format all match. Re-confirm once on the first real charge in case the API
    has moved since.
 3. Smallest-value real mobile-money charge to your own phone: USSD push
    appears -> approve -> billing page poll flips to paid -> Premium active ->
    receipt email lands.
 4. Register https://<host>/api/payments/webhook/lenco/<LENCO_WEBHOOK_SECRET>/
    in the Lenco dashboard; repeat a charge and confirm the webhook settles it
    before the poller does. Confirm the webhook payload's reference field name
    matches _extract_reference() below.
 5. One real card charge through the widget; confirm verify-by-reference
    settles it (the widget callback alone never activates anything).
 6. Production hardening: set ALLOWED_HOSTS, replace CORS_ALLOW_ALL_ORIGINS
    with the real frontend origin, webhook URL must be HTTPS.
"""
import os
import uuid

import requests

from .base import PaymentGatewayError, PaymentNotConfigured, PaymentProvider

# ---- Lenco API surface  VERIFY AGAINST docs.lenco.co ON FIRST LIVE TEST ----
LENCO_BASE_URL = os.environ.get("LENCO_BASE_URL") or "https://api.lenco.co/access/v2"
PATH_CREATE_MOMO = "/collections/mobile-money"
PATH_SUBMIT_OTP = "/collections/mobile-money/submit-otp"
PATH_STATUS_BY_REF = "/collections/status/{reference}"  # lookup by OUR reference
DEFAULT_WIDGET_URL = "https://pay.lenco.co/js/v1/inline.js"

OPERATOR_MAP = {"mtn_momo": "mtn", "airtel_money": "airtel"}

# Lenco status -> our tri-state. Anything unknown maps to "pending" (the safe
# default: a poller retries; nothing is ever activated off an unknown status).
STATUS_MAP = {
    "successful": "paid",
    "success": "paid",
    "settled": "paid",
    "failed": "failed",
    "cancelled": "failed",
    "expired": "failed",
    "pending": "pending",
    "pay-offline": "pending",
    "otp-required": "pending",
    "processing": "pending",
}

# "local" -> 0961234567 ; "international" -> 260961234567
# Verified 2026-07-29 against the live Lenco API (docs + two working client
# libraries, alexasomba/lenco-node & kapansa/lenco-payment-gateway): the
# mobile-money endpoint expects the MSISDN in international form ("2609XXXXXXXX").
PHONE_FORMAT = "international"

# The country the mobile-money collection is settled in. Lenco accounts can span
# NG/ZM; the documented field is a lowercase ISO code and every reference client
# sends it. Zambia-only here (mobile money is ZMW by construction).
MOMO_COUNTRY = "zm"

REQUEST_TIMEOUT_SECONDS = 20
# -----------------------------------------------------------------------------


def _api_key():
    key = (os.environ.get("LENCO_API_KEY") or "").strip()
    if not key:
        raise PaymentNotConfigured("LENCO_API_KEY is not set.")
    return key


def _public_key():
    key = (os.environ.get("LENCO_PUBLIC_KEY") or "").strip()
    if not key:
        raise PaymentNotConfigured("LENCO_PUBLIC_KEY is not set (needed for card payments).")
    return key


def format_phone(phone):
    """Normalize any accepted Zambian input (+260..., 260..., 09..., 9...) to
    the format Lenco expects (PHONE_FORMAT constant)."""
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("260"):
        national = digits[3:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits
    return f"0{national}" if PHONE_FORMAT == "local" else f"260{national}"


class LencoProvider(PaymentProvider):
    """All methods read the secret key lazily per call  the server always
    boots with a blank key, and unconfigured calls fail as a clean 503.
    The secret key is never stored on the instance and never logged (log only
    our reference + HTTP status codes)."""

    def _request(self, http_method, path, payload=None):
        url = f"{LENCO_BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            response = requests.request(
                http_method, url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            raise PaymentGatewayError(f"Lenco unreachable: {exc.__class__.__name__}") from exc

        try:
            data = response.json()
        except ValueError:
            raise PaymentGatewayError(f"Lenco returned non-JSON (HTTP {response.status_code}).")

        if response.status_code >= 400:
            message = data.get("message") or "unknown error"
            print(f"[lenco] HTTP {response.status_code} on {path}: {message}")
            raise PaymentGatewayError(f"Lenco error (HTTP {response.status_code}): {message}")
        return data

    @staticmethod
    def _extract_status(data):
        """Dig the transaction status out of a Lenco response defensively 
        checks data.data.status, then data.status."""
        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        raw = (inner.get("status") or data.get("status") or "").lower()
        return STATUS_MAP.get(raw, "pending")

    def create_charge(self, *, user, price=None, currency, phone, method, pack=None):
        from accounts.models import Payment  # local import avoids an app-loading-order issue

        from .fx import charge_amount

        # ZMW charges use the real-time USD→ZMW market rate; USD charges use
        # the admin-entered amount as-is. Snapshotted here  a later rate
        # movement never changes what this payment recorded.
        amount = charge_amount(pack or price, currency)

        # Our own reference, created BEFORE any gateway call: there is never
        # money movement without a Payment row to reconcile against.
        ref = f"cr_{uuid.uuid4().hex}"
        payment = Payment.objects.create(
            user=user,
            provider="lenco",
            provider_ref=ref,
            amount=amount,
            currency=currency,
            method=method,
            period_days=price.period_days if price else 0,
            price=price,
            pack=pack,
            credits_amount=pack.credits if pack else 0,
            status="pending",
        )

        if method == "card":
            # Card runs through Lenco's inline widget in the browser using the
            # PUBLIC key only; the backend later confirms by reference via
            # verify()  the widget callback alone never activates anything.
            try:
                public_key = _public_key()
            except PaymentNotConfigured:
                # Same rule as the mobile-money path below: nothing reached the
                # customer, so don't leave a dangling pending row behind.
                payment.status = "failed"
                payment.save(update_fields=["status", "updated_at"])
                raise
            return {
                "ref": ref,
                "card": {
                    "public_key": public_key,
                    "reference": ref,
                    "amount": str(amount),
                    "currency": currency,
                    "email": user.email,
                    "widget_url": os.environ.get("LENCO_WIDGET_URL") or DEFAULT_WIDGET_URL,
                },
            }

        # Mobile money: server-side initiation triggers a USSD approval push
        # on the customer's phone. Always ZMW (enforced by the view).
        try:
            data = self._request(
                "POST",
                PATH_CREATE_MOMO,
                {
                    # Lenco's mobile-money schema declares amount as a number
                    # (double) and has no `currency` field  the currency is
                    # implied by `country`/`operator` (always ZMW here). Sending
                    # a numeric amount + country, matching the reference clients.
                    "amount": float(amount),
                    "reference": ref,
                    "phone": format_phone(phone),
                    "operator": OPERATOR_MAP[method],
                    "country": MOMO_COUNTRY,
                    "bearer": "merchant",
                },
            )
        except (PaymentNotConfigured, PaymentGatewayError):
            # No charge reached the customer  don't leave a dangling pending row.
            payment.status = "failed"
            payment.save(update_fields=["status", "updated_at"])
            raise

        status = self._extract_status(data)
        inner = data.get("data") if isinstance(data.get("data"), dict) else {}
        if (inner.get("status") or "").lower() == "otp-required":
            return {"ref": ref, "otp_required": True, "prompt": "Enter the OTP sent to your phone to approve the payment."}
        if status == "failed":
            payment.status = "failed"
            payment.save(update_fields=["status", "updated_at"])
            return {"ref": ref, "status": "failed", "prompt": "The payment could not be started. Please try again."}
        return {
            "ref": ref,
            "prompt": (
                "Approve the payment prompt on your phone. If no prompt appears, "
                "open your operator's mobile-money menu and approve the pending payment."
            ),
        }

    def verify(self, provider_ref: str) -> str:
        try:
            data = self._request("GET", PATH_STATUS_BY_REF.format(reference=provider_ref))
        except (PaymentNotConfigured, PaymentGatewayError):
            # A transient gateway blip must never fail a real charge  report
            # pending and let the poller/webhook retry.
            return "pending"
        return self._extract_status(data)

    def submit_otp(self, provider_ref: str, otp: str) -> str:
        data = self._request("POST", PATH_SUBMIT_OTP, {"reference": provider_ref, "otp": otp})
        return self._extract_status(data)

    def handle_webhook(self, request):
        """The payload is treated as an untrusted hint: we only extract the
        reference, then re-verify server-side against the Lenco API before
        reporting any status  so a forged webhook can never mark anything
        paid, regardless of Lenco's signature scheme."""
        import json

        try:
            payload = json.loads(request.body or b"{}")
        except (ValueError, AttributeError):
            return {"ref": None, "status": "pending"}

        ref = self._extract_reference(payload)
        if not ref:
            return {"ref": None, "status": "pending"}
        return {"ref": ref, "status": self.verify(ref)}

    @staticmethod
    def _extract_reference(payload):
        """Webhook payload shape is uncertain until the first live test 
        probe the plausible locations for our reference."""
        if not isinstance(payload, dict):
            return None
        inner = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        for candidate in (
            inner.get("reference"),
            inner.get("transactionReference"),
            payload.get("reference"),
            payload.get("transactionReference"),
        ):
            if candidate and isinstance(candidate, str):
                return candidate
        return None
