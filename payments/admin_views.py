"""Superuser-only price management for the admin Engine Room (Pricing tab).

The admin sets price options here; they reflect immediately on the public
pricing endpoint, the pricing page, and the billing page's upgrade flow 
one source of truth (payments.models.PlanPrice) read everywhere.
"""
import json
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from accounts.decorators import superuser_required

from . import fx
from .models import PlanPrice


def _admin_price_json(price, rate_info):
    return {
        "id": price.id,
        "label": price.label,
        "plan": price.plan,
        "display_amount_usd": str(price.display_amount_usd),
        # Computed live  the admin only ever enters the USD price.
        "amount_zmw": str(fx.zmw_amount(price.display_amount_usd, fx=rate_info)),
        "period_days": price.period_days,
        "is_active": price.is_active,
        "sort_order": price.sort_order,
        "created_at": price.created_at.isoformat(),
        "updated_at": price.updated_at.isoformat(),
    }


def _validated_fields(body, *, partial):
    """Validate and coerce PlanPrice fields from a request body.
    Returns (fields_dict, error_response)."""
    fields = {}

    if "label" in body or not partial:
        label = (body.get("label") or "").strip()
        if not label or len(label) > 80:
            return None, JsonResponse({"error": "invalid_label", "message": "Label is required (max 80 chars)."}, status=400)
        fields["label"] = label

    if "display_amount_usd" in body or not partial:
        try:
            value = Decimal(str(body.get("display_amount_usd", "")))
        except (InvalidOperation, TypeError):
            return None, JsonResponse({"error": "invalid_display_amount_usd", "message": "'display_amount_usd' must be a number."}, status=400)
        if value <= 0 or value > Decimal("99999999"):
            return None, JsonResponse({"error": "invalid_display_amount_usd", "message": "'display_amount_usd' must be greater than 0."}, status=400)
        fields["display_amount_usd"] = value.quantize(Decimal("0.01"))

    if "period_days" in body or not partial:
        period_days = body.get("period_days", 30)
        if not isinstance(period_days, int) or not (1 <= period_days <= 3650):
            return None, JsonResponse({"error": "invalid_period_days", "message": "'period_days' must be 1–3650."}, status=400)
        fields["period_days"] = period_days

    if "is_active" in body:
        if not isinstance(body["is_active"], bool):
            return None, JsonResponse({"error": "invalid_is_active"}, status=400)
        fields["is_active"] = body["is_active"]

    if "sort_order" in body:
        sort_order = body["sort_order"]
        if not isinstance(sort_order, int) or not (0 <= sort_order <= 999):
            return None, JsonResponse({"error": "invalid_sort_order"}, status=400)
        fields["sort_order"] = sort_order

    return fields, None


def _parse_json_body(request):
    try:
        return json.loads(request.body or b"{}"), None
    except (ValueError, UnicodeDecodeError):
        return None, JsonResponse({"error": "invalid_json"}, status=400)


@csrf_exempt
@superuser_required
def admin_prices_view(request):
    """GET: all price options (active and inactive). POST: create one."""
    if request.method == "GET":
        rate_info = fx.get_usd_to_zmw()
        return JsonResponse(
            {
                "prices": [_admin_price_json(p, rate_info) for p in PlanPrice.objects.all()],
                "fx": fx.fx_json(rate_info),
            }
        )

    if request.method == "POST":
        body, error = _parse_json_body(request)
        if error:
            return error
        fields, error = _validated_fields(body, partial=False)
        if error:
            return error
        price = PlanPrice.objects.create(**fields)
        print(f"[cockpit] {request.user.email} created price option: {price}")
        return JsonResponse({"price": _admin_price_json(price, fx.get_usd_to_zmw())}, status=201)

    return JsonResponse({"error": "method_not_allowed"}, status=405)


@csrf_exempt
@superuser_required
def admin_price_detail_view(request, price_id):
    """PATCH: partial update. DELETE: remove (payment history survives via
    SET_NULL, but deactivating is preferred once real payments reference it)."""
    try:
        price = PlanPrice.objects.get(pk=price_id)
    except PlanPrice.DoesNotExist:
        return JsonResponse({"error": "price_not_found"}, status=404)

    if request.method == "PATCH":
        body, error = _parse_json_body(request)
        if error:
            return error
        fields, error = _validated_fields(body, partial=True)
        if error:
            return error
        for key, value in fields.items():
            setattr(price, key, value)
        price.save()
        print(f"[cockpit] {request.user.email} updated price option {price.pk}: {sorted(fields)}")
        return JsonResponse({"price": _admin_price_json(price, fx.get_usd_to_zmw())})

    if request.method == "DELETE":
        had_payments = price.payments.exists()
        label = price.label
        price.delete()
        print(f"[cockpit] {request.user.email} DELETED price option '{label}' (id={price_id})")
        message = f"'{label}' deleted."
        if had_payments:
            message += " Note: past payments referenced this option  prefer deactivating instead of deleting next time."
        return JsonResponse({"message": message})

    return JsonResponse({"error": "method_not_allowed"}, status=405)
