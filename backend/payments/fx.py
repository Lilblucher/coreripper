"""Live USD→ZMW exchange rate for pricing.

The admin enters prices in USD only; the Kwacha amount charged to Zambian
customers is computed from the real-time market rate (the same mid-market rate
Google Finance displays  Google has no public API, so we read it from free
market-rate feeds instead, overridable via FX_API_URL).

Resolution chain, honesty-first at every step:
  1. Django cache (fresh fetch within the last hour)  source "live"
  2. Fetch from the provider list                      source "live"
  3. Last successfully fetched rate stored in the DB   source "stored"
  4. FX_FALLBACK_USD_ZMW env (default below)           source "fallback"
The source + fetch time travel with the rate everywhere it's shown, so the
frontend can say "at today's rate" only when it actually is today's rate.
"""
import os
from datetime import timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import requests
from django.core.cache import cache
from django.utils import timezone

# ---- FX providers  free, keyless market-rate feeds (checked in order) ----
FX_API_URLS = [
    url
    for url in [
        os.environ.get("FX_API_URL", "").strip() or None,
        "https://open.er-api.com/v6/latest/USD",
        "https://api.frankfurter.app/latest?from=USD&to=ZMW",
    ]
    if url
]
FALLBACK_USD_ZMW = os.environ.get("FX_FALLBACK_USD_ZMW", "27.00")

CACHE_KEY = "fx_usd_zmw_v1"
CACHE_SECONDS = 3600  # re-fetch at most hourly
FAILURE_CACHE_SECONDS = 600  # don't hammer providers (or hang offline) on every request
REQUEST_TIMEOUT_SECONDS = 10
# ---------------------------------------------------------------------------

TWO_DP = Decimal("0.01")


def _parse_rate(data):
    """Both supported feeds return {"rates": {"ZMW": <number>}}."""
    try:
        return Decimal(str(data["rates"]["ZMW"]))
    except (KeyError, TypeError, InvalidOperation):
        return None


def _fetch_live_rate():
    for url in FX_API_URLS:
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code != 200:
                continue
            rate = _parse_rate(response.json())
            if rate and rate > 0:
                return rate, url
        except (requests.RequestException, ValueError):
            continue
    return None, None


def get_usd_to_zmw():
    """Returns {"rate": Decimal, "source": "live"|"stored"|"fallback",
    "fetched_at": datetime|None}. Never raises; never hits the network more
    than once per cache window."""
    from .models import FxRate

    cached = cache.get(CACHE_KEY)
    if cached:
        return {
            "rate": Decimal(cached["rate"]),
            "source": cached["source"],
            "fetched_at": cached["fetched_at"],
        }

    rate, url = _fetch_live_rate()
    if rate is not None:
        now = timezone.now()
        FxRate.objects.update_or_create(
            pair="USD/ZMW", defaults={"rate": rate, "source": url, "fetched_at": now}
        )
        result = {"rate": rate, "source": "live", "fetched_at": now}
        cache.set(CACHE_KEY, {"rate": str(rate), "source": "live", "fetched_at": now}, CACHE_SECONDS)
        return result

    # Offline / providers down: last successfully fetched rate, then env fallback.
    stored = FxRate.objects.filter(pair="USD/ZMW").first()
    if stored:
        result = {"rate": stored.rate, "source": "stored", "fetched_at": stored.fetched_at}
    else:
        result = {"rate": Decimal(FALLBACK_USD_ZMW), "source": "fallback", "fetched_at": None}
    cache.set(
        CACHE_KEY,
        {"rate": str(result["rate"]), "source": result["source"], "fetched_at": result["fetched_at"]},
        FAILURE_CACHE_SECONDS,
    )
    return result


def zmw_amount(usd_amount, fx=None):
    """Kwacha equivalent of a USD amount at the current rate, 2dp."""
    fx = fx or get_usd_to_zmw()
    return (Decimal(usd_amount) * fx["rate"]).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def charge_amount(price, currency, fx=None):
    """The server-side amount actually charged for a PlanPrice in a given
    currency  the single place charge amounts come from (clients never send
    amounts). USD charges use the admin-entered price as-is; ZMW charges use
    the live-rate conversion."""
    if currency == "USD":
        return Decimal(price.display_amount_usd).quantize(TWO_DP)
    return zmw_amount(price.display_amount_usd, fx=fx)


def fx_json(fx=None):
    """Rate metadata for API responses  lets the frontend label the rate
    honestly ('today's rate' vs 'last known rate')."""
    fx = fx or get_usd_to_zmw()
    fetched = fx["fetched_at"]
    if fetched and timezone.is_naive(fetched):
        fetched = fetched.replace(tzinfo=dt_timezone.utc)
    return {
        "usd_to_zmw": str(fx["rate"]),
        "source": fx["source"],
        "fetched_at": fetched.isoformat() if fetched else None,
    }
