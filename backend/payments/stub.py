"""StubProvider  lets the entire subscription/gating/premium-tool flow be built and
tested today, with zero payment-gateway dependency (implementation spec, section 6).

It creates real Payment rows in 'pending' status. There is deliberately no automatic
path to 'paid' here: a site admin confirms payments received off-platform (mobile
money sent directly, WhatsApp, etc.) via the "Mark selected payments as paid &
activate Premium" action in Django admin (see accounts/admin.py). That's a legitimate
soft-launch  real users can be onboarded manually before any gateway goes live.
"""
import uuid

from .base import PaymentProvider


class StubProvider(PaymentProvider):
    def create_charge(self, *, user, price=None, currency, phone, method, pack=None):
        from accounts.models import Payment  # local import avoids an app-loading-order issue

        from .fx import charge_amount

        ref = f"stub_{uuid.uuid4().hex[:16]}"
        Payment.objects.create(
            user=user,
            provider="stub",
            provider_ref=ref,
            amount=charge_amount(pack or price, currency),
            currency=currency,
            method=method,
            period_days=price.period_days if price else 0,
            price=price,
            pack=pack,
            credits_amount=pack.credits if pack else 0,
            status="pending",
        )
        thing = "add the credits" if pack else "activate Premium"
        return {
            "ref": ref,
            "prompt": (
                f"This isn't a real payment gateway yet. To {thing} manually, "
                "send payment via mobile money and a site admin will confirm it in the "
                "admin panel."
            ),
        }

    def verify(self, provider_ref: str) -> str:
        from accounts.models import Payment

        try:
            return Payment.objects.get(provider="stub", provider_ref=provider_ref).status
        except Payment.DoesNotExist:
            return "failed"

    def handle_webhook(self, request):
        # The stub has no real webhook source. This exists only so local dev/tests can
        # simulate one: POST {"ref": "...", "status": "paid"} and the matching Payment
        # (if any) is updated. Never wire an unauthenticated endpoint like this to a
        # real provider  real adapters must verify a signature/secret first.
        import json

        from accounts.models import Payment

        try:
            payload = json.loads(request.body or b"{}")
        except (ValueError, AttributeError):
            payload = {}

        ref = payload.get("ref")
        status = payload.get("status", "paid")
        if not ref:
            return {"ref": None, "status": "failed"}

        updated = Payment.objects.filter(provider="stub", provider_ref=ref).update(status=status)
        return {"ref": ref, "status": status if updated else "failed"}
