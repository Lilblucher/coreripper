"""Seed the ScamRule and ScamShortener tables with the data that was
previously hardcoded in scam_detector.py."""

from django.db import migrations


RULES = [
    ("PIN_OTP_REQUEST", 20,
     r"\b(pin|otp|one[- ]?time (?:code|password)|verification code)\b[^.\n]{0,25}\b(share|send|confirm|provide|give|reply with)\b",
     "Asks you to share a PIN, OTP, or verification code"),
    ("PIN_OTP_REQUEST_REV", 20,
     r"\b(share|send|confirm|provide|give|reply with)\b[^.\n]{0,25}\b(pin|otp|one[- ]?time (?:code|password)|verification code)\b",
     "Asks you to share a PIN, OTP, or verification code"),
    ("FEE_TO_RECEIVE", 15,
     r"\b(pay|send|deposit|transfer)\b[^.\n]{0,40}\b(registration|processing|activation|insurance|clearance|verification)?\s?fee\b",
     "Asks you to pay a fee before you can receive money or a job"),
    ("MM_REVERSAL", 15,
     r"\b(sent (?:it|money|funds)? ?by mistake|wrong number[,.]? (?:please )?(?:send|reverse)|please reverse|reverse (?:it|the transaction|this payment)|send it back)\b",
     "Claims money was sent by mistake and asks you to send it back"),
    ("MONEY_PER_TIME", 15,
     r"\b(k|zmw|kwacha)\s?\d{2,5}(\s?[-–]\s?\d{2,5})?\s?(per\s?day|daily|/\s?day|a\s?day|per\s?week)\b",
     "Promises a fixed amount of money per day/week"),
    ("MONEY_PER_TIME_REV", 15,
     r"\b\d{2,5}(\s?[-–]\s?\d{2,5})?\s?(k|zmw|kwacha)\s?(per\s?day|daily|/\s?day|a\s?day|per\s?week)\b",
     "Promises a fixed amount of money per day/week"),
    ("UNSOLICITED_GOODNEWS", 12,
     r"\b(you\W?ve been (selected|shortlisted|chosen)|your application (?:was|has been) (?:successful|approved)|congratulations,? you)\b",
     "Unsolicited good news (\"you've been selected/approved\")"),
    ("URGENCY", 10,
     r"\b(act now|verify now|immediately|within 24\s?hours?|account will be (?:blocked|suspended|closed)|urgently)\b",
     "Creates urgency to pressure a fast reply"),
    ("PRIZE_LOTTERY", 10,
     r"\b(won|winner|lottery|prize)\b[^.\n]{0,40}\b(claim|fee|airtime|to receive)\b",
     "Prize/lottery win that requires a fee or airtime to claim"),
    ("WHATSAPP_HANDOFF", 12,
     r"(wa\.me/|api\.whatsapp\.com/send|message (?:me|us) on (?:whatsapp|telegram)|contact (?:me|us) (?:on|via) (?:whatsapp|telegram))",
     "Pushes you off to WhatsApp/Telegram to continue"),
    ("LOAN_GUARANTEE", 15,
     r"\b(guaranteed loan|loan (?:is )?approved|instant loan)\b[^.\n]{0,40}\b(fee|upfront|processing)\b",
     "Guaranteed loan approval that requires an upfront fee"),
    ("GENERIC_GREETING", 5,
     r"^\s*(dear customer|hello dear|dear valued customer)\b",
     "Generic greeting typical of bulk scam messages"),
]

SHORTENERS = [
    "bit.ly", "tinyurl.com", "cutt.ly", "t.co", "is.gd", "rebrand.ly",
    "tiny.cc", "rb.gy", "shorturl.at", "ow.ly", "buff.ly", "s.id",
]


def seed(apps, schema_editor):
    ScamRule = apps.get_model('network_tools', 'ScamRule')
    ScamShortener = apps.get_model('network_tools', 'ScamShortener')

    for code, weight, pattern, label in RULES:
        ScamRule.objects.get_or_create(
            code=code,
            defaults={
                'weight': weight,
                'pattern': pattern,
                'label': label,
                'source': 'seed',
            },
        )

    for domain in SHORTENERS:
        ScamShortener.objects.get_or_create(
            domain=domain,
            defaults={'source': 'seed'},
        )


def unseed(apps, schema_editor):
    ScamRule = apps.get_model('network_tools', 'ScamRule')
    ScamShortener = apps.get_model('network_tools', 'ScamShortener')
    ScamRule.objects.filter(source='seed').delete()
    ScamShortener.objects.filter(source='seed').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('network_tools', '0001_scam_rules_shorteners_breach_alerts'),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
