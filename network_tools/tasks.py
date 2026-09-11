"""Periodic tasks for keeping the Scam Detector and Password Breach Checker
resources up to date. Registered by data migration 0003."""

import json
import logging
import re

import requests
from celery import shared_task
from django.utils import timezone

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scam Detector: AI-powered rule refresh
# ---------------------------------------------------------------------------

_SCAM_RULE_PROMPT = """You are a fraud-detection pattern engineer. Your job is to produce NEW
regex-based scam detection rules for SMS and WhatsApp messages, focusing on
patterns that are currently trending in Sub-Saharan Africa, Southeast Asia,
and globally.

Current rule codes already in the system (do NOT duplicate these):
{existing_codes}

Current shortener domains already tracked:
{existing_shorteners}

Generate NEW rules and shortener domains that cover emerging scam patterns
not yet in the list above. Think about:
- Crypto/investment scams ("guaranteed returns", "mining pool")
- SIM swap social engineering ("your SIM will be deactivated")
- Fake government/tax refund messages
- Fake delivery/parcel notifications
- Romance/dating app scams moving to WhatsApp
- Job scams on social media ("work from home", "data entry")
- Fake bank security alerts
- QR code phishing
- New URL shortener domains that scammers use

Respond with ONLY valid JSON in this exact format, no other text:
{{
  "rules": [
    {{
      "code": "UNIQUE_CODE_NAME",
      "weight": 10,
      "pattern": "regex pattern here (Python re syntax, case-insensitive)",
      "label": "Human-readable description of what this catches"
    }}
  ],
  "shorteners": ["domain1.com", "domain2.com"]
}}

Rules:
- code must be UPPERCASE_SNAKE_CASE, unique, max 80 chars
- weight: 5-20 (5=weak signal, 10=moderate, 15=strong, 20=very strong)
- pattern: valid Python regex, case-insensitive flag applied automatically
- label: 1 sentence, user-facing, describes the red flag
- Only include rules you're confident about, not speculative ones
- Generate 3-8 new rules and 0-5 new shortener domains
"""


@shared_task(name='network_tools.update_scam_patterns')
def update_scam_patterns():
    """Use AI (free model) to generate new scam detection patterns based on
    current trends. Runs weekly via Celery Beat."""
    from network_tools.models import ScamRule, ScamShortener, ScamUpdateLog
    from network_tools.scam_detector import invalidate_cache

    existing_codes = list(
        ScamRule.objects.filter(is_active=True).values_list('code', flat=True)
    )
    existing_shorteners = list(
        ScamShortener.objects.filter(is_active=True).values_list('domain', flat=True)
    )

    prompt = _SCAM_RULE_PROMPT.format(
        existing_codes=', '.join(existing_codes),
        existing_shorteners=', '.join(existing_shorteners),
    )

    try:
        from credits.services import run_ai
        result = run_ai(
            user=None,
            operation='scam_pattern_update',
            system_prompt='You are a fraud-detection pattern engineer. Respond with valid JSON only.',
            user_message=prompt,
        )
    except Exception as e:
        log.warning('Scam pattern AI update failed: %s', e)
        return f'AI call failed: {e}'

    ai_text = result.get('content', '') if isinstance(result, dict) else str(result)

    json_match = re.search(r'\{[\s\S]*\}', ai_text)
    if not json_match:
        log.warning('Scam pattern AI returned no JSON')
        return 'No JSON in AI response'

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        log.warning('Scam pattern AI returned invalid JSON: %s', e)
        return f'Invalid JSON: {e}'

    rules_added = 0
    rules_updated = 0
    shorteners_added = 0
    details = []

    for rule in data.get('rules', []):
        code = rule.get('code', '').strip().upper()
        pattern = rule.get('pattern', '').strip()
        weight = rule.get('weight', 10)
        label = rule.get('label', '').strip()

        if not code or not pattern or not label:
            continue
        if len(code) > 80:
            continue

        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error:
            details.append(f'Skipped {code}: invalid regex')
            continue

        weight = max(1, min(20, int(weight)))

        obj, created = ScamRule.objects.update_or_create(
            code=code,
            defaults={
                'weight': weight,
                'pattern': pattern,
                'label': label,
                'source': 'ai',
                'is_active': True,
            },
        )
        if created:
            rules_added += 1
            details.append(f'Added rule: {code} (w={weight})')
        else:
            rules_updated += 1
            details.append(f'Updated rule: {code}')

    for domain in data.get('shorteners', []):
        domain = domain.strip().lower()
        if not domain or len(domain) > 100:
            continue
        _, created = ScamShortener.objects.get_or_create(
            domain=domain,
            defaults={'source': 'auto', 'is_active': True},
        )
        if created:
            shorteners_added += 1
            details.append(f'Added shortener: {domain}')

    if rules_added or rules_updated or shorteners_added:
        invalidate_cache()

    ScamUpdateLog.objects.create(
        rules_added=rules_added,
        rules_updated=rules_updated,
        shorteners_added=shorteners_added,
        source='ai',
        details='\n'.join(details),
    )

    summary = f'+{rules_added} rules, ~{rules_updated} updated, +{shorteners_added} shorteners'
    log.info('Scam pattern update: %s', summary)
    return summary


# ---------------------------------------------------------------------------
# Password Breach Checker: recent breach alerts from HIBP
# ---------------------------------------------------------------------------

HIBP_BREACHES_URL = 'https://haveibeenpwned.com/api/v3/breaches'


@shared_task(name='network_tools.fetch_breach_alerts')
def fetch_breach_alerts():
    """Fetch the latest breaches from HIBP's public API and store them
    so the frontend can show recent breach context. Runs weekly."""
    from network_tools.models import BreachAlert

    try:
        resp = requests.get(
            HIBP_BREACHES_URL,
            headers={'User-Agent': 'CoreRipper-BreachChecker'},
            timeout=30,
        )
        resp.raise_for_status()
        breaches = resp.json()
    except Exception as e:
        log.warning('HIBP breach fetch failed: %s', e)
        return f'Fetch failed: {e}'

    now = timezone.now()
    added = 0
    updated = 0

    for b in breaches:
        name = b.get('Name', '')
        if not name:
            continue

        defaults = {
            'title': b.get('Title', name),
            'domain': b.get('Domain', ''),
            'breach_date': b.get('BreachDate') or None,
            'added_date': b.get('AddedDate', '')[:10] if b.get('AddedDate') else None,
            'pwn_count': b.get('PwnCount', 0),
            'description': b.get('Description', ''),
            'data_classes': b.get('DataClasses', []),
            'is_verified': b.get('IsVerified', False),
            'is_active': not b.get('IsRetired', False),
            'fetched_at': now,
        }

        obj, created = BreachAlert.objects.update_or_create(
            name=name, defaults=defaults,
        )
        if created:
            added += 1
        else:
            updated += 1

    summary = f'+{added} new, ~{updated} updated breaches'
    log.info('Breach alert fetch: %s', summary)
    return summary
