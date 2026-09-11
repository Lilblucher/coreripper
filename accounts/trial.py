"""Guest trial enforcement  3 free operations per tool for logged-out visitors.

Backed by Django's cache (currently LocMemCache  per-process, resets on server
restart; move to Redis before running multiple workers, per settings.py). We
deliberately don't use django-ratelimit: it isn't installed and can't be
pip-installed on this offline box, and the cache is enough for this.

Guest identity  Stage 1 keys off **client IP**. That works today across the
frontend(:5501)/API(:8000) origin split with no frontend changes, and (unlike a
freshly-set cookie) has no mid-trial identity discontinuity. Its known weakness
is over-blocking shared IPs (offices/VPNs). Stage 2 should layer a server-set
`cr_anon` HttpOnly cookie as the *precise* primary key (taking precedence over
IP when present)  that needs the frontend to send `credentials: 'include'` and
CORS switched from allow-all to a specific origin with `CORS_ALLOW_CREDENTIALS`.
`get_anon_id` already prefers the cookie if one is ever present, so Stage 2 is
purely additive.
"""

import os
from datetime import date

from django.core.cache import cache
from django.utils import timezone

TRIAL_LIMIT = 3
ANON_COOKIE = "cr_anon"

# Free-account daily cap across ALL local tools (op-count, not $). Spec's
# placeholder number, env-tunable without a deploy. Premium is never counted.
FREE_DAILY_OP_LIMIT = int(os.environ.get("FREE_DAILY_OP_LIMIT", "50"))


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "0.0.0.0")


def get_anon_id(request):
    """Stable-ish identity for an accountless visitor: the `cr_anon` cookie if
    one is present (Stage 2), else the client IP (Stage 1)."""
    cookie = request.COOKIES.get(ANON_COOKIE)
    if cookie:
        return f"cookie:{cookie}"
    return f"ip:{_client_ip(request)}"


def trial_remaining(anon_id, tool_key, limit=TRIAL_LIMIT):
    return max(0, limit - cache.get(f"trial:{anon_id}:{tool_key}", 0))


def check_and_increment_trial(anon_id, tool_key, limit=TRIAL_LIMIT):
    """Consume one trial op for (anon_id, tool_key). Returns True if allowed
    (and increments), False if the 3-op trial for this tool is exhausted.
    No time expiry  the trial resets on signup (a Free account isn't gated by
    this counter), not on a clock."""
    key = f"trial:{anon_id}:{tool_key}"
    count = cache.get(key, 0)
    if count >= limit:
        return False
    cache.set(key, count + 1, timeout=None)
    return True


def check_and_increment_free_quota(user, limit=None):
    """Daily op-count quota for Free (logged-in, unpaid) accounts on LOCAL
    tools  one shared counter per user per calendar day, across all local
    tools. Returns (allowed, remaining_after). Same LocMemCache caveat as the
    trial counter: per-process, resets on server restart; a restart being
    slightly generous is acceptable, silently blocking early would not be."""
    if limit is None:
        limit = FREE_DAILY_OP_LIMIT
    key = f"freequota:{user.id}:{date.today().isoformat()}"
    count = cache.get(key, 0)
    if count >= limit:
        return False, 0
    # 26h TTL: outlives its calendar day (key includes the date, so a stale
    # entry can never be read tomorrow), then evicts itself.
    cache.set(key, count + 1, timeout=60 * 60 * 26)
    return True, limit - (count + 1)


def free_quota_remaining(user, limit=None):
    if limit is None:
        limit = FREE_DAILY_OP_LIMIT
    return max(0, limit - cache.get(f"freequota:{user.id}:{date.today().isoformat()}", 0))


# --- Per-tool, per-period quotas (plan entitlements) ----------------------
# Used for tools the pricing page caps per plan rather than per day (currently
# the AI-Crawler Checker: 3/week free, 30/mo Lite, 100/mo Standard, 20/hr Pro).
# Same cache-counter approach as above; the key embeds the period bucket, so a
# stale entry can never be read in the next period and the TTL is just cleanup.
_PERIOD_TTL_SECONDS = {"hour": 60 * 70, "week": 60 * 60 * 24 * 8, "month": 60 * 60 * 24 * 32}


def _period_bucket(period, now=None):
    now = now or timezone.now()
    if period == "hour":
        return now.strftime("%Y%m%d%H")
    if period == "week":
        iso = now.isocalendar()
        return f"{iso[0]}W{iso[1]:02d}"
    if period == "month":
        return now.strftime("%Y%m")
    raise ValueError(f"Unknown quota period {period!r}")


def _tool_quota_key(user_id, tool_key, period, now=None):
    return f"toolquota:{user_id}:{tool_key}:{period}:{_period_bucket(period, now)}"


def check_and_increment_tool_quota(user, tool_key, limit, period, now=None):
    """Consume one op against a per-tool periodic cap.
    Returns (allowed, remaining_after). A `limit` of None means uncapped."""
    if limit is None:
        return True, None
    key = _tool_quota_key(user.id, tool_key, period, now)
    count = cache.get(key, 0)
    if count >= limit:
        return False, 0
    cache.set(key, count + 1, timeout=_PERIOD_TTL_SECONDS[period])
    return True, limit - (count + 1)


def tool_quota_remaining(user, tool_key, limit, period, now=None):
    if limit is None:
        return None
    return max(0, limit - cache.get(_tool_quota_key(user.id, tool_key, period, now), 0))
