"""Read-only credit endpoints for the frontend credit meter (header chip +
dropdown breakdown + usage history). No AI call routing lives here  that's
credits/services.py::run_ai(); this module only reports wallet state.
"""
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import AIUsageRecord, CreditLedger, CreditWallet


def _login_required_json(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "login_required"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


def _state_for(total):
    if total <= 0:
        return "zero"
    if total < settings.CREDIT_LOW_BALANCE_THRESHOLD:
        return "low"
    return "normal"


@require_GET
@_login_required_json
def wallet_view(request):
    """Balance for the header chip + dropdown. Pack credits never expire per
    lot until PACK_CREDIT_LIFETIME_DAYS out, so `pack_expires_at` surfaces the
    earliest-expiring unexpired lot (or null if the user has none)."""
    wallet, _ = CreditWallet.objects.get_or_create(user=request.user)
    sub = getattr(request.user, "subscription", None)
    earliest_lot = wallet.pack_lots.order_by("expires_at").first()

    return JsonResponse(
        {
            "subscription_balance": wallet.subscription_balance,
            "pack_balance": wallet.pack_balance,
            "total_balance": wallet.total_balance,
            "state": _state_for(wallet.total_balance),
            "low_threshold": settings.CREDIT_LOW_BALANCE_THRESHOLD,
            "plan": getattr(sub, "plan", "free"),
            "subscription_refresh_at": sub.current_period_end.isoformat() if sub and sub.current_period_end else None,
            "earliest_pack_expiry": earliest_lot.expires_at.isoformat() if earliest_lot else None,
        }
    )


@require_GET
@_login_required_json
def usage_history_view(request):
    """Recent AI usage + ledger movements, newest first, for the meter
    dropdown's "usage history" link. Capped  this is a glance view, not an
    export (dashboard/Workbench already owns bulk export)."""
    limit = 50
    usage = list(
        AIUsageRecord.objects.filter(user=request.user).order_by("-created_at")[:limit].values(
            "operation", "model", "tokens_in", "tokens_out", "credits_charged", "created_at"
        )
    )
    ledger = list(
        CreditLedger.objects.filter(user=request.user).order_by("-created_at")[:limit].values(
            "delta", "bucket", "reason", "operation", "balance_after", "created_at"
        )
    )
    return JsonResponse({"usage": usage, "ledger": ledger})
