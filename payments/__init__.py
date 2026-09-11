"""Callers always go through get_provider()  never import StubProvider/LencoProvider/
LipilaProvider directly. That's what makes the gateway swap a one-line env change.
"""
import os

_PROVIDER_INSTANCE = None


def get_provider():
    global _PROVIDER_INSTANCE
    if _PROVIDER_INSTANCE is not None:
        return _PROVIDER_INSTANCE

    name = os.environ.get("PAYMENT_PROVIDER", "stub").lower()

    if name == "stub":
        from .stub import StubProvider

        _PROVIDER_INSTANCE = StubProvider()
    elif name == "lenco":
        # Real adapter. Reads LENCO_API_KEY lazily per call, so the server
        # boots fine before the key arrives  unconfigured calls return a
        # clean 503 gateway_not_configured instead of crashing.
        from .lenco import LencoProvider

        _PROVIDER_INSTANCE = LencoProvider()
    elif name == "lipila":
        # Not implemented yet  build once Lipila approves and their API docs are in hand.
        raise NotImplementedError(
            "PAYMENT_PROVIDER=lipila but payments/lipila.py doesn't exist yet."
        )
    else:
        raise ValueError(f"Unknown PAYMENT_PROVIDER={name!r}. Expected stub|lenco|lipila.")

    return _PROVIDER_INSTANCE
