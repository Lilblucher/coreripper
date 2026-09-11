"""The 'AI Knowledge' layer: generates/refreshes hardware.models.HardwareAIProfile,
the structured (not prose-only) buyer-facing knowledge for one device
best_for tags, strengths, trade-offs, expected lifespan, recommended RAM/SSD.

Regeneration is gated on `source_spec_hash`  a sha256 of the device's
tracked spec fields  so this only runs when the underlying facts actually
changed, never on a timer and never on a no-op sync. Uses
run_ai(user=None, ...) (credits.services), the same free-model-only pattern
as news.services' news_draft call, so generating knowledge for a public
catalog page never touches anyone's wallet.
"""
import hashlib
import json

from credits.services import run_ai

from .spec_fields import TRACKED_SPEC_FIELDS
from .models import HardwareAIProfile

SYSTEM_PROMPT = (
    "You are CoreRipper's hardware desk. Given a device's specifications, "
    "produce a short buyer's-guide profile as STRICT JSON with exactly these "
    "keys: best_for (array of up to 5 short tags like \"Students\", "
    "\"Programming\", \"Office\", \"Gaming\", \"Video Editing\"), strengths "
    "(array of up to 4 short phrases), trade_offs (array of up to 3 short "
    "phrases), expected_lifespan_years (short string like \"5+ years\"), "
    "recommended_ram_gb (integer or null), recommended_ssd_gb (integer or "
    "null), verdict_text (2-3 plain-English sentences). This is CoreRipper's "
    "own editorial opinion  never attribute it to PassMark, GSMArena, "
    "Notebookcheck, or any other outside source. Reply with ONLY the JSON "
    "object, no markdown fences, no commentary."
)


def _tracked_fields(type_key):
    _, fields = TRACKED_SPEC_FIELDS[type_key]
    return [name for name, _label in fields]


def compute_spec_hash(instance, type_key):
    values = {f: str(getattr(instance, f, None)) for f in _tracked_fields(type_key)}
    payload = json.dumps(values, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _spec_summary_text(instance, type_key):
    lines = [f"Device: {instance}"]
    for f in _tracked_fields(type_key):
        value = getattr(instance, f, None)
        if value not in (None, ""):
            lines.append(f"{f}: {value}")
    return "\n".join(lines)


def _parse_profile_json(raw_text):
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # A truncated response (cut off mid-string by the max_tokens cap) sometimes
    # still has a clean outermost { ... } span once trimmed to the last
    # complete top-level brace.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    # Last resort: the response was cut off entirely before its closing
    # brace(s)  a single unterminated string is the common case (verdict_text
    # is the last, longest field), so try closing the string and the object.
    if start != -1:
        for repair in ('"}', "}"):
            try:
                return json.loads(text[start:] + repair)
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("Could not repair truncated JSON", text, 0)


def generate_profile(instance, type_key):
    """Create or refresh the HardwareAIProfile for one device if its tracked
    spec fields have changed since the last generation (or no profile exists
    yet). Returns the profile, or None if generation was skipped (hash
    unchanged) or failed (parse/AI error  logged, existing profile left
    untouched rather than corrupted with partial data)."""
    new_hash = compute_spec_hash(instance, type_key)
    existing = HardwareAIProfile.objects.filter(type_key=type_key, object_id=instance.pk).first()
    if existing and existing.source_spec_hash == new_hash:
        return None  # no real spec change since the last generation

    try:
        result = run_ai(
            user=None,
            operation="hardware_knowledge",
            system=SYSTEM_PROMPT,
            user_msg=_spec_summary_text(instance, type_key),
        )
        parsed = _parse_profile_json(result["content"])
    except Exception as exc:  # noqa: BLE001  a bad AI response must not crash the sync
        print(f"[ai_knowledge] profile generation failed for {type_key}#{instance.pk}: {exc}")
        return None

    profile, _created = HardwareAIProfile.objects.update_or_create(
        type_key=type_key,
        object_id=instance.pk,
        defaults={
            "best_for": parsed.get("best_for") or [],
            "strengths": parsed.get("strengths") or [],
            "trade_offs": parsed.get("trade_offs") or [],
            "expected_lifespan_years": (parsed.get("expected_lifespan_years") or "")[:60],
            "recommended_ram_gb": parsed.get("recommended_ram_gb") or None,
            "recommended_ssd_gb": parsed.get("recommended_ssd_gb") or None,
            "verdict_text": parsed.get("verdict_text") or "",
            "source_spec_hash": new_hash,
        },
    )
    return profile
