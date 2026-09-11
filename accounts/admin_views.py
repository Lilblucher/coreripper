"""Superuser-only user management for the admin engine room.

Staff (is_staff) accounts exist ONLY to write blog posts  blog authoring
endpoints stay staff_required (see blog/views.py), but everything here
(user list, deletion, subscription changes, staff promotion, transactions)
is superuser_required.
"""
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .decorators import is_admin, superuser_required
from .models import Payment, Subscription
from .subscription_utils import has_active_paid_subscription


def _admin_user_json(user):
    sub = getattr(user, "subscription", None)
    return {
        "id": user.id,
        "email": user.email,
        "date_joined": user.date_joined.isoformat(),
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "is_admin": is_admin(user),
        "is_active": user.is_active,
        "plan": sub.plan if sub else "free",
        "is_premium": sub.is_premium if sub else False,
        "subscription_active": sub.is_premium if sub else False,
        "status": sub.status if sub else "expired",
        "renewal_state": sub.renewal_state if sub else "not_due",
        "current_period_end": sub.current_period_end.isoformat() if sub and sub.current_period_end else None,
        "expires_at": sub.expires_at.isoformat() if sub and sub.expires_at else None,
        # True when current Premium came from a real settled payment  the
        # Engine Room disables the manual plan dropdown for these users.
        "paid_subscriber": has_active_paid_subscription(user),
    }


def _transaction_json(payment):
    return {
        "id": payment.id,
        "user_email": payment.user.email,
        "provider": payment.provider,
        "provider_ref": payment.provider_ref,
        "method": payment.method,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "status": payment.status,
        "created_at": payment.created_at.isoformat(),
        "updated_at": payment.updated_at.isoformat(),
    }


@require_GET
@superuser_required
def admin_users_view(request):
    users = User.objects.select_related("subscription").order_by("-date_joined")
    return JsonResponse({"users": [_admin_user_json(u) for u in users]})


@require_GET
@superuser_required
def admin_transactions_view(request):
    payments = Payment.objects.select_related("user").order_by("-created_at")
    return JsonResponse({"transactions": [_transaction_json(p) for p in payments]})


@csrf_exempt
@superuser_required
def admin_user_detail_view(request, user_id):
    """PATCH: change subscription (plan/trial) or staff status.
    DELETE: remove the user and every row they own (all User FKs cascade 
    verified when account deletion was built). The 5-second countdown lives
    in the frontend; the backend just refuses the two irreversible mistakes:
    deleting yourself, or touching another superuser."""
    try:
        target = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({"error": "user_not_found"}, status=404)

    if request.method == "DELETE":
        if target.id == request.user.id:
            return JsonResponse(
                {"error": "cannot_delete_self", "message": "Use Settings → Delete account for your own account."},
                status=400,
            )
        if target.is_superuser:
            return JsonResponse(
                {"error": "cannot_delete_superuser", "message": "Superuser accounts can't be deleted from here."},
                status=400,
            )
        email = target.email
        target.delete()
        print(f"[cockpit] {request.user.email} DELETED user {email} (id={user_id})")
        return JsonResponse({"message": f"{email} deleted."})

    if request.method == "PATCH":
        try:
            body = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"error": "invalid_json"}, status=400)

        if target.is_superuser and target.id != request.user.id:
            return JsonResponse(
                {"error": "cannot_modify_superuser", "message": "Another superuser's account can't be changed."},
                status=400,
            )

        changed = []

        if "is_staff" in body:
            if not isinstance(body["is_staff"], bool):
                return JsonResponse({"error": "invalid_is_staff"}, status=400)
            target.is_staff = body["is_staff"]
            target.save(update_fields=["is_staff"])
            changed.append(f"staff={'yes' if target.is_staff else 'no'}")

        if "plan" in body:
            if has_active_paid_subscription(target):
                return JsonResponse(
                    {
                        "error": "paid_subscriber",
                        "message": (
                            "This user paid for their subscription  their plan is managed "
                            "by the payment system until it expires."
                        ),
                    },
                    status=409,
                )
            plan = body["plan"]
            # "premium" accepted as a legacy alias for "pro".
            if plan == "premium":
                plan = "pro"
            paid_tiers = ("lite", "standard", "pro")
            if plan not in ("free",) + paid_tiers:
                return JsonResponse(
                    {"error": "invalid_plan", "message": "Plan must be one of free/lite/standard/pro."},
                    status=400,
                )
            from django.conf import settings as _settings
            from credits.models import CreditWallet

            sub, _ = Subscription.objects.get_or_create(user=target)
            sub.plan = plan
            trial_days = 0
            if plan in paid_tiers:
                # trial_days: a free trial of the tier. Omitted/0 = no expiry (paid).
                trial_days = body.get("trial_days") or 0
                if not isinstance(trial_days, int) or trial_days < 0 or trial_days > 365:
                    return JsonResponse({"error": "invalid_trial_days"}, status=400)
                sub.status = "trialing" if trial_days else "active"
                sub.renewal_state = "not_due"
                sub.current_period_start = timezone.now()
                end = timezone.now() + timedelta(days=trial_days) if trial_days else None
                sub.current_period_end = end
                sub.expires_at = end
            else:
                sub.status = "expired"
                sub.renewal_state = "not_due"
                sub.current_period_end = None
                sub.expires_at = None
            sub.save()
            wallet, _ = CreditWallet.objects.get_or_create(user=target)
            wallet.reset_subscription(_settings.TIER_MONTHLY_CREDITS.get(plan, 0))
            changed.append(f"plan={plan}" + (f" (trial {trial_days}d)" if plan in paid_tiers and trial_days else ""))

        if changed:
            print(f"[cockpit] {request.user.email} changed {target.email}: {', '.join(changed)}")
        return JsonResponse({"user": _admin_user_json(User.objects.select_related("subscription").get(id=target.id))})

    return JsonResponse({"error": "method_not_allowed"}, status=405)
