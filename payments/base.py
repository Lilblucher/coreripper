"""Provider-agnostic payment adapter interface.

Every part of the app that needs to charge a user depends on this interface,
never on a specific provider, so that swapping gateways is a single new adapter
file plus one env var flip (PAYMENT_PROVIDER).

Security invariant: create_charge takes a PlanPrice, not an amount  the amount
charged is always resolved server-side from the pricing table. No client input
ever decides what a subscription costs.
"""
from abc import ABC, abstractmethod


class PaymentNotConfigured(Exception):
    """The selected provider is missing its API key/config. Raised lazily at
    call time (mirrors core.llm.LLMNotConfigured) so the server always boots;
    views turn this into a 503 'gateway_not_configured'."""


class PaymentGatewayError(Exception):
    """The gateway was unreachable or returned an unusable response; views
    turn this into a 502."""


class PaymentNotSupported(Exception):
    """The provider doesn't implement this operation (e.g. OTP on the stub)."""


class PaymentProvider(ABC):
    @abstractmethod
    def create_charge(self, *, user, price=None, currency, phone, method, pack=None):
        """Initiate a charge for a payments.models.PlanPrice (subscription) or
        a payments.models.CreditPackPrice (one-time Claude-credit pack)
        exactly one of price/pack is given; both carry display_amount_usd, so
        payments.fx.charge_amount works on either. Charged in the given
        currency ("ZMW"  live-rate Kwacha conversion  or "USD", the
        admin-entered amount as-is; see payments.fx.charge_amount, the single
        place charge amounts come from).

        The adapter must create the pending accounts.Payment row itself,
        snapshotting amount/currency/method/period_days/price (or
        credits_amount/pack for pack purchases)  history must survive later
        price edits and rate movements.

        Returns a dict with at least {"ref": str}. May also include:
          "prompt"         human-readable instruction (e.g. "Approve the
                            USSD prompt on your phone")
          "otp_required"   True when the operator wants an OTP submitted
                            via submit_otp()
          "card"           dict of public widget parameters for card flows
                            (public key, reference, amount, currency, email,
                            widget_url); never any secret material
        """

    @abstractmethod
    def verify(self, provider_ref: str) -> str:
        """Server-side verification of a charge. Never trust a client-side
        redirect or widget callback alone  always call this (or
        handle_webhook) before activating a subscription. Returns one of:
        'paid', 'pending', 'failed'.
        """

    @abstractmethod
    def handle_webhook(self, request):
        """Parse an inbound provider webhook.

        Returns a dict {"ref": str|None, "status": "paid"|"pending"|"failed"}.
        Must never trust the payload's own status claim  re-verify against
        the gateway (or authenticate a signature) before reporting 'paid'.
        """

    def submit_otp(self, provider_ref: str, otp: str) -> str:
        """Submit an operator OTP for a charge that returned otp_required.
        Returns 'paid'|'pending'|'failed'. Providers without an OTP step keep
        this default."""
        raise PaymentNotSupported("This payment provider has no OTP step.")
