"""Admin API for managing scam detection rules and shortener domains,
plus a public endpoint for recent breach alerts."""

import json
import re

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from accounts.decorators import superuser_required


# ---------------------------------------------------------------------------
# Public: recent breach alerts (read-only, for the breach checker page)
# ---------------------------------------------------------------------------

@require_GET
def breach_alerts_view(request):
    """Return the most recent notable breaches for display context."""
    from network_tools.models import BreachAlert

    limit = min(int(request.GET.get('limit', 10)), 50)
    alerts = BreachAlert.objects.filter(
        is_active=True, is_verified=True,
    ).order_by('-breach_date')[:limit]

    return JsonResponse({
        'status': 'success',
        'alerts': [
            {
                'name': a.name,
                'title': a.title,
                'domain': a.domain,
                'breach_date': str(a.breach_date) if a.breach_date else None,
                'pwn_count': a.pwn_count,
                'data_classes': a.data_classes[:5],
                'is_verified': a.is_verified,
            }
            for a in alerts
        ],
    })


# ---------------------------------------------------------------------------
# Admin: scam rules CRUD
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
@superuser_required
def admin_scam_rules_view(request):
    from network_tools.models import ScamRule

    if request.method == 'GET':
        rules = ScamRule.objects.all()
        source_filter = request.GET.get('source')
        if source_filter:
            rules = rules.filter(source=source_filter)

        return JsonResponse({
            'status': 'success',
            'rules': [
                {
                    'id': r.id,
                    'code': r.code,
                    'weight': r.weight,
                    'pattern': r.pattern,
                    'label': r.label,
                    'is_active': r.is_active,
                    'source': r.source,
                    'created_at': r.created_at.isoformat(),
                }
                for r in rules
            ],
        })

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    code = (data.get('code') or '').strip().upper()
    pattern = (data.get('pattern') or '').strip()
    label = (data.get('label') or '').strip()
    weight = data.get('weight', 10)

    if not code or not pattern or not label:
        return JsonResponse({'status': 'error', 'message': 'code, pattern, and label are required'}, status=400)

    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return JsonResponse({'status': 'error', 'message': f'Invalid regex: {e}'}, status=400)

    weight = max(1, min(20, int(weight)))

    rule, created = ScamRule.objects.update_or_create(
        code=code,
        defaults={
            'weight': weight,
            'pattern': pattern,
            'label': label,
            'source': 'admin',
            'is_active': data.get('is_active', True),
        },
    )

    from network_tools.scam_detector import invalidate_cache
    invalidate_cache()

    return JsonResponse({
        'status': 'success',
        'created': created,
        'rule': {
            'id': rule.id,
            'code': rule.code,
            'weight': rule.weight,
            'pattern': rule.pattern,
            'label': rule.label,
            'is_active': rule.is_active,
            'source': rule.source,
        },
    }, status=201 if created else 200)


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
@superuser_required
def admin_scam_rule_detail_view(request, rule_id):
    from network_tools.models import ScamRule

    try:
        rule = ScamRule.objects.get(id=rule_id)
    except ScamRule.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Not found'}, status=404)

    if request.method == 'DELETE':
        rule.delete()
        from network_tools.scam_detector import invalidate_cache
        invalidate_cache()
        return JsonResponse({'status': 'success'})

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    if 'pattern' in data:
        try:
            re.compile(data['pattern'], re.IGNORECASE)
        except re.error as e:
            return JsonResponse({'status': 'error', 'message': f'Invalid regex: {e}'}, status=400)
        rule.pattern = data['pattern']

    if 'weight' in data:
        rule.weight = max(1, min(20, int(data['weight'])))
    if 'label' in data:
        rule.label = data['label']
    if 'is_active' in data:
        rule.is_active = bool(data['is_active'])

    rule.save()

    from network_tools.scam_detector import invalidate_cache
    invalidate_cache()

    return JsonResponse({
        'status': 'success',
        'rule': {
            'id': rule.id,
            'code': rule.code,
            'weight': rule.weight,
            'pattern': rule.pattern,
            'label': rule.label,
            'is_active': rule.is_active,
            'source': rule.source,
        },
    })


# ---------------------------------------------------------------------------
# Admin: shortener domains
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET", "POST"])
@superuser_required
def admin_scam_shorteners_view(request):
    from network_tools.models import ScamShortener

    if request.method == 'GET':
        return JsonResponse({
            'status': 'success',
            'shorteners': [
                {
                    'id': s.id,
                    'domain': s.domain,
                    'is_active': s.is_active,
                    'source': s.source,
                }
                for s in ScamShortener.objects.all()
            ],
        })

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)

    domain = (data.get('domain') or '').strip().lower()
    if not domain:
        return JsonResponse({'status': 'error', 'message': 'domain is required'}, status=400)

    obj, created = ScamShortener.objects.get_or_create(
        domain=domain,
        defaults={'source': 'admin', 'is_active': True},
    )

    from network_tools.scam_detector import invalidate_cache
    invalidate_cache()

    return JsonResponse({
        'status': 'success',
        'created': created,
        'shortener': {'id': obj.id, 'domain': obj.domain, 'is_active': obj.is_active},
    }, status=201 if created else 200)


@csrf_exempt
@require_http_methods(["DELETE"])
@superuser_required
def admin_scam_shortener_detail_view(request, shortener_id):
    from network_tools.models import ScamShortener

    try:
        obj = ScamShortener.objects.get(id=shortener_id)
    except ScamShortener.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Not found'}, status=404)

    obj.delete()

    from network_tools.scam_detector import invalidate_cache
    invalidate_cache()

    return JsonResponse({'status': 'success'})


# ---------------------------------------------------------------------------
# Admin: update logs
# ---------------------------------------------------------------------------

@require_GET
@superuser_required
def admin_scam_update_logs_view(request):
    from network_tools.models import ScamUpdateLog

    logs = ScamUpdateLog.objects.all()[:20]
    return JsonResponse({
        'status': 'success',
        'logs': [
            {
                'id': l.id,
                'run_at': l.run_at.isoformat(),
                'rules_added': l.rules_added,
                'rules_updated': l.rules_updated,
                'shorteners_added': l.shorteners_added,
                'source': l.source,
                'details': l.details,
            }
            for l in logs
        ],
    })
