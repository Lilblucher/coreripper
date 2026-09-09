"""The one place that talks to the Octavian WhatsApp bot.

The bot is a separate Node process (`whatsapp_bot.js`) holding a live WhatsApp
Web session, exposing a localhost-only `POST /send`. Nothing in Django controls
whether that process is up or whether its WhatsApp session is still linked, so
every function here reports failure honestly rather than raising  callers
persist the reason (AlertLog.whatsapp_error) or surface it to the user.

Why a probe of `POST /send` with an empty body is the availability check:
the bot answers `503` when its WhatsApp client isn't ready and only *then*
validates the payload, returning `400` for a missing number/message. So an
empty POST distinguishes all three states with **no message actually sent**:

    connection error -> bot process is down
    503             -> bot is up but its WhatsApp session isn't linked
    400             -> bot is up and linked, i.e. a real send would go through

Don't "tidy" that into a GET /health  the bot has no such route, and adding
one means editing a process that lives outside this repo.
"""

import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

SEND_TIMEOUT_SECONDS = 10
PROBE_TIMEOUT_SECONDS = 4

# Short enough that linking the bot mid-session shows up quickly, long enough
# that rendering the monitor form doesn't hit the bot on every render.
STATUS_CACHE_KEY = "monitors:whatsapp:status"
STATUS_CACHE_SECONDS = 60

# States reported back to the frontend. Only "ready" means a send will land.
READY = "ready"
UNLINKED = "unlinked"
OFFLINE = "offline"

_STATE_MESSAGES = {
    READY: "WhatsApp alerts are ready to send.",
    UNLINKED: "The WhatsApp sender is running but isn't linked to a WhatsApp account yet.",
    OFFLINE: "The WhatsApp sender is offline, so WhatsApp alerts can't be delivered right now.",
}


def _send_url():
    return settings.WHATSAPP_BOT_URL.rstrip("/") + "/send"


def send_message(number, message):
    """Send one WhatsApp message. Returns (sent: bool, error: str).

    `error` is a short human-readable reason on failure and "" on success  it
    is stored on AlertLog.whatsapp_error and shown in the dashboard, so keep it
    user-facing, not a raw exception repr.
    """
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    if not digits:
        return False, "No WhatsApp number on file."

    try:
        resp = requests.post(
            _send_url(),
            json={"number": digits, "message": message},
            timeout=SEND_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("WhatsApp send failed (transport): %s", exc)
        return False, _STATE_MESSAGES[OFFLINE]

    if resp.status_code == 503:
        return False, _STATE_MESSAGES[UNLINKED]

    try:
        payload = resp.json()
    except ValueError:
        payload = {}

    if resp.ok and payload.get("status") == "sent":
        return True, ""

    # The bot echoes a real reason for a rejected number / send failure; prefer
    # it over a generic string so a wrong number is distinguishable from an
    # outage. Trimmed to fit AlertLog.whatsapp_error.
    reason = (payload.get("message") or "").strip()
    logger.warning("WhatsApp send failed (%s): %s", resp.status_code, reason or resp.text[:200])
    return False, (reason or f"The WhatsApp sender rejected the message (HTTP {resp.status_code}).")[:200]


def probe_status(use_cache=True):
    """Return {"state", "available", "message"} for the bot, cached briefly.

    Never raises  an unreachable bot is a normal, expected answer here.
    """
    if use_cache:
        cached = cache.get(STATUS_CACHE_KEY)
        if cached is not None:
            return cached

    try:
        resp = requests.post(_send_url(), json={}, timeout=PROBE_TIMEOUT_SECONDS)
        # 400 == "up, linked, and you just didn't give me a number" (see module docstring).
        state = READY if resp.status_code == 400 else UNLINKED if resp.status_code == 503 else UNLINKED
    except requests.RequestException:
        state = OFFLINE

    status = {"state": state, "available": state == READY, "message": _STATE_MESSAGES[state]}
    cache.set(STATUS_CACHE_KEY, status, STATUS_CACHE_SECONDS)
    return status


def invalidate_status_cache():
    """Called after a real send attempt, whose outcome is fresher than the probe."""
    cache.delete(STATUS_CACHE_KEY)
