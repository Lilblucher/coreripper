"""
Scam Detector - scam/phishing risk scoring for pasted SMS/WhatsApp text.

Rules and shortener domains are stored in the DB (ScamRule / ScamShortener)
so they can be updated at runtime - via the Engine Room, management commands,
or the periodic AI-powered update task - without a code deploy.

The DB is read through a short cache (~5 min) and falls back to the original
hardcoded seed data if the DB is unreachable (e.g. during migrations).
"""

import logging
import re
import urllib.parse

from django.core.cache import cache

log = logging.getLogger(__name__)

_F = re.IGNORECASE

# ---------------------------------------------------------------------------
# Hardcoded fallbacks (the original seed data, kept as a safety net)
# ---------------------------------------------------------------------------

_SEED_RULES = [
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
     r"(wa\\.me/|api\\.whatsapp\\.com/send|message (?:me|us) on (?:whatsapp|telegram)|contact (?:me|us) (?:on|via) (?:whatsapp|telegram))",
     "Pushes you off to WhatsApp/Telegram to continue"),
    ("LOAN_GUARANTEE", 15,
     r"\b(guaranteed loan|loan (?:is )?approved|instant loan)\b[^.\n]{0,40}\b(fee|upfront|processing)\b",
     "Guaranteed loan approval that requires an upfront fee"),
    ("GENERIC_GREETING", 5,
     r"^\s*(dear customer|hello dear|dear valued customer)\b",
     "Generic greeting typical of bulk scam messages"),
]

_SEED_SHORTENERS = {
    "bit.ly", "tinyurl.com", "cutt.ly", "t.co", "is.gd", "rebrand.ly",
    "tiny.cc", "rb.gy", "shorturl.at", "ow.ly", "buff.ly", "s.id",
}

# ---------------------------------------------------------------------------
# DB-backed rule/shortener loading (cached, with fallback)
# ---------------------------------------------------------------------------

_RULES_CACHE_KEY = 'scam_rules_v1'
_SHORTENERS_CACHE_KEY = 'scam_shorteners_v1'
_CACHE_TTL = 300  # 5 minutes


def _load_rules():
    """Return list of (code, weight, compiled_pattern, label) from the DB."""
    cached = None
    try:
        cached = cache.get(_RULES_CACHE_KEY)
    except Exception:
        pass
    if cached is not None:
        return cached

    try:
        from network_tools.models import ScamRule
        rows = ScamRule.objects.filter(is_active=True).values_list(
            'code', 'weight', 'pattern', 'label',
        )
        compiled = []
        for code, weight, pattern, label in rows:
            try:
                compiled.append((code, weight, re.compile(pattern, _F), label))
            except re.error:
                log.warning('Invalid regex in ScamRule %s: %s', code, pattern)
        if compiled:
            try:
                cache.set(_RULES_CACHE_KEY, compiled, _CACHE_TTL)
            except Exception:
                pass
            return compiled
    except Exception:
        log.debug('ScamRule table not available, using seed fallback')

    fallback = [(c, w, re.compile(p, _F), l) for c, w, p, l in _SEED_RULES]
    return fallback


def _load_shorteners():
    """Return a set of shortener domains from the DB."""
    cached = None
    try:
        cached = cache.get(_SHORTENERS_CACHE_KEY)
    except Exception:
        pass
    if cached is not None:
        return cached

    try:
        from network_tools.models import ScamShortener
        domains = set(
            ScamShortener.objects.filter(is_active=True)
            .values_list('domain', flat=True)
        )
        if domains:
            try:
                cache.set(_SHORTENERS_CACHE_KEY, domains, _CACHE_TTL)
            except Exception:
                pass
            return domains
    except Exception:
        log.debug('ScamShortener table not available, using seed fallback')

    return set(_SEED_SHORTENERS)


def invalidate_cache():
    """Call after admin edits or an auto-update run."""
    try:
        cache.delete(_RULES_CACHE_KEY)
        cache.delete(_SHORTENERS_CACHE_KEY)
    except Exception:
        pass


TEXT_RULE_CAP = 60

# ---------------------------------------------------------------------------
# Link analysis
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_WA_RE = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=)(\d{6,15})", re.IGNORECASE)


def _find_urls(text):
    return _URL_RE.findall(text)


def _extract_wa_numbers(text):
    return _WA_RE.findall(text)


def _is_shortener(url):
    shorteners = _load_shorteners()
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        host = host.split("@")[-1].split(":")[0]
        return host in shorteners
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Phone analysis
# ---------------------------------------------------------------------------

COUNTRIES = {
    "ZM": ("Zambia", "260"), "ZW": ("Zimbabwe", "263"), "MW": ("Malawi", "265"),
    "LS": ("Lesotho", "266"), "BW": ("Botswana", "267"), "SZ": ("Eswatini", "268"),
    "NG": ("Nigeria", "234"), "KE": ("Kenya", "254"), "TZ": ("Tanzania", "255"),
    "UG": ("Uganda", "256"), "GH": ("Ghana", "233"), "ET": ("Ethiopia", "251"),
    "EG": ("Egypt", "20"), "ZA": ("South Africa", "27"),
    "GB": ("United Kingdom", "44"), "IE": ("Ireland", "353"),
    "US": ("United States / Canada", "1"),
    "IN": ("India", "91"), "PK": ("Pakistan", "92"), "BD": ("Bangladesh", "880"),
    "CN": ("China", "86"), "PH": ("Philippines", "63"), "ID": ("Indonesia", "62"),
    "AE": ("United Arab Emirates", "971"), "SA": ("Saudi Arabia", "966"),
    "HK": ("Hong Kong", "852"), "SG": ("Singapore", "65"), "MY": ("Malaysia", "60"),
    "AU": ("Australia", "61"), "NZ": ("New Zealand", "64"),
    "DE": ("Germany", "49"), "FR": ("France", "33"), "ES": ("Spain", "34"),
    "IT": ("Italy", "39"), "BR": ("Brazil", "55"), "MX": ("Mexico", "52"),
}
CALLING_CODE_TO_COUNTRY = {code: name for name, code in COUNTRIES.values()}
_SORTED_CODES = sorted(CALLING_CODE_TO_COUNTRY.keys(), key=len, reverse=True)

_PHONE_CANDIDATE_RE = re.compile(r"(?<!\d)(\+?\d[\d\-\s]{6,14}\d)(?!\d)")


def _collect_phone_candidates(text, wa_numbers):
    candidates = ["+" + n for n in wa_numbers]
    for raw in _PHONE_CANDIDATE_RE.findall(text):
        cleaned = re.sub(r"[\s\-]", "", raw)
        if cleaned not in candidates:
            candidates.append(cleaned)
    return candidates


def _guess_country(candidate):
    digits = candidate[1:] if candidate.startswith("+") else None
    if digits is None:
        return None, None
    for code in _SORTED_CODES:
        if digits.startswith(code):
            return CALLING_CODE_TO_COUNTRY[code], code
    return None, None


# ---------------------------------------------------------------------------
# Scoring / fusion
# ---------------------------------------------------------------------------

def _band(score):
    if score >= 70:
        return "High"
    if score >= 30:
        return "Suspicious"
    return "Low"


def _advice(flag_codes, band):
    if "PIN_OTP_REQUEST" in flag_codes or "PIN_OTP_REQUEST_REV" in flag_codes:
        return ("Never share a PIN, OTP, or verification code with anyone - no legitimate bank, "
                "mobile money agent, or employer will ever ask for one. Do not reply.")
    if "MM_REVERSAL" in flag_codes:
        return ("This matches a common mobile-money reversal scam: no money was actually sent to you. "
                "Do not send anything back - verify directly with your mobile money provider first.")
    if flag_codes & {"FEE_TO_RECEIVE", "MONEY_PER_TIME", "MONEY_PER_TIME_REV", "PRIZE_LOTTERY", "LOAN_GUARANTEE"}:
        return ("This looks like a task/job/prize scam. Legitimate employers and lotteries never ask you "
                "to pay a fee up front. Do not pay, and verify any employer through an official, "
                "independently-found contact.")
    if band == "High":
        return "This message shows strong scam indicators. Do not click links, pay money, or share personal details."
    if band == "Suspicious":
        return "This message shows some scam indicators. Proceed carefully and verify independently before acting."
    return "No strong scam indicators found, but always verify unexpected money or job offers independently."


DISCLAIMER = (
    "This is a risk estimate, not a verdict. We can't and won't reveal who owns a phone number - "
    "that data is private and legally protected almost everywhere. We only show country-code "
    "consistency (if you tell us your country), link patterns, and message red flags."
)

LIMITATIONS = [
    "No ML text classifier yet: this scan is rules + link + phone signals only (no in-process "
    "TF-IDF/Naive Bayes model - that stage needs a labelled training corpus, not yet available).",
    "Phone analysis uses a small built-in calling-code table, not Google's libphonenumber "
    "(unavailable in this environment) - only country-code mismatch is detected, not line type or validity.",
]


def scan_message(text, region_hint=""):
    text = (text or "").strip()
    if not text:
        return {"status": "error", "message": "Please paste a message to scan."}
    if len(text) > 6000:
        return {"status": "error", "message": "Message is too long (max 6000 characters)."}

    rules = _load_rules()

    flags = []
    fired_codes = set()
    rule_points = 0
    for code, weight, pattern, label in rules:
        m = pattern.search(text)
        if not m:
            continue
        display_code = code.replace("_REV", "")
        if display_code in fired_codes:
            continue
        fired_codes.add(display_code)
        fired_codes.add(code)
        flags.append({"code": display_code, "label": label, "detail": f"matched \"{m.group(0).strip()}\""})
        rule_points += weight
    rule_points = min(rule_points, TEXT_RULE_CAP)

    urls = _find_urls(text)
    wa_numbers = _extract_wa_numbers(text)
    link_points = 0
    link_ran = bool(urls) or bool(wa_numbers)

    if wa_numbers and "WHATSAPP_HANDOFF" not in fired_codes:
        flags.append({
            "code": "WHATSAPP_HANDOFF",
            "label": "Pushes you off to WhatsApp/Telegram to continue",
            "detail": f"wa.me/{wa_numbers[0]}",
        })
        fired_codes.add("WHATSAPP_HANDOFF")
        link_points += 8

    shortener_hit = next((u for u in urls if _is_shortener(u)), None)
    if shortener_hit:
        flags.append({
            "code": "SHORTENER_LINK",
            "label": "Uses a link shortener that hides the real destination",
            "detail": shortener_hit,
        })
        link_points += 6

    phone_candidates = _collect_phone_candidates(text, wa_numbers)
    phone_ran = bool(phone_candidates)
    phone_points = 0
    home = COUNTRIES.get((region_hint or "").upper())
    home_name, home_code = home if home else (None, None)

    if home_code:
        for raw in phone_candidates:
            if not raw.startswith("+"):
                continue
            country, code = _guess_country(raw)
            if country and code != home_code:
                if "COUNTRY_MISMATCH" not in fired_codes:
                    flags.append({
                        "code": "COUNTRY_MISMATCH",
                        "label": f"A number in this message is registered to {country}, not {home_name}",
                        "detail": f"{raw} -> +{code} ({country})",
                    })
                    fired_codes.add("COUNTRY_MISMATCH")
                    phone_points += 20
                break

    combo_points = 0
    money_codes = {"MONEY_PER_TIME", "FEE_TO_RECEIVE", "PRIZE_LOTTERY", "LOAN_GUARANTEE", "MM_REVERSAL"}
    if "WHATSAPP_HANDOFF" in fired_codes and "COUNTRY_MISMATCH" in fired_codes and (fired_codes & money_codes):
        flags.append({
            "code": "COMBO_FOREIGN_CONTACT_MONEY",
            "label": "A foreign WhatsApp contact plus a money promise is riskier together than either alone",
            "detail": "wa.me handoff + country-code mismatch + a money/fee signal all fired on this message",
        })
        combo_points = 15

    total = max(0, min(100, rule_points + link_points + phone_points + combo_points))
    band = _band(total)

    result = {
        "status": "success",
        "result": {
            "score": total,
            "band": band,
            "analyzers_run": {
                "text_rules": True,
                "text_ml": False,
                "link": link_ran,
                "phone": phone_ran,
                "country_check": bool(home_code),
            },
            "flags": flags,
            "advice": _advice(fired_codes, band),
            "disclaimer": DISCLAIMER,
            "limitations": LIMITATIONS,
        },
    }

    # Include rule count so the frontend can show "scanning with N patterns"
    result["result"]["rule_count"] = len(rules)

    return result
