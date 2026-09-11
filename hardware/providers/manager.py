"""The provider manager: merges partial records from every *live* spec
provider into real CPU/GPU/Laptop/MobileSoC rows, tracks per-field
provenance (HardwareFieldSource), logs real changes (HardwareSpecChange),
records/dedupes images (HardwareDeviceImage), and triggers AI-knowledge
regeneration only when a device's tracked specs actually changed.

Curated fields (performance_score/value_score/etc.) and admin-uploaded
images (is_admin_override=True) are never written here  those are
human-curation fields by design (see hardware/models.py's own field
comments) and this function must never clobber them.
"""
import hashlib

from django.utils import timezone

from .. import ai_knowledge
from ..models import (
    CPU,
    GPU,
    HardwareDeviceImage,
    HardwareFieldSource,
    HardwareSpecChange,
    Laptop,
    MobileSoC,
)
from .field_priority import FIELD_PRIORITY, LIVE_PROVIDERS, priority_for

MODELS_BY_TYPE = {"cpu": CPU, "gpu": GPU, "laptop": Laptop, "mobile_soc": MobileSoC}


def _merge_provider_records(type_key):
    """{name_key: {provider_key: record_dict}} across every live provider's
    fetch() output for this type. name_key (lowercased device name) is the
    cross-provider join key  provider-specific external_ids differ per
    source, so name is the only key guaranteed to be comparable across more
    than one provider once a second one is ever wired in."""
    per_name = {}
    for provider_key, provider in LIVE_PROVIDERS.items():
        try:
            records = provider.fetch(type_key)
        except Exception as exc:  # noqa: BLE001  one dead provider must not break the others
            print(f"[manager] provider '{provider_key}' failed for {type_key!r}: {exc}")
            continue
        for rec in records:
            name_key = (rec.get("name") or "").strip().lower()
            if not name_key:
                continue
            per_name.setdefault(name_key, {})[provider_key] = rec
    return per_name


def _resolve_field(type_key, field_name, provider_records):
    for provider_key in priority_for(type_key, field_name):
        rec = provider_records.get(provider_key)
        if rec and rec.get(field_name) is not None:
            return provider_key, rec[field_name]
    return None, None


def _find_existing_row(model, provider_records):
    # Prefer a match on external_id (a previously-synced row); fall back to
    # a case-insensitive name+manufacturer match so a hand-curated seed row
    # is matched instead of duplicated once a provider also knows about it.
    for rec in provider_records.values():
        ext_id = rec.get("external_id")
        if ext_id:
            row = model.objects.filter(external_id=ext_id).first()
            if row:
                return row
    any_rec = next(iter(provider_records.values()))
    name, manufacturer = any_rec.get("name"), any_rec.get("manufacturer")
    if name:
        qs = model.objects.filter(name__iexact=name)
        if manufacturer:
            qs = qs.filter(manufacturer__iexact=manufacturer)
        return qs.first()
    return None


def _record_image(type_key, object_id, url, source_url, provider_key):
    if not url:
        return
    if len(url) > 1000:
        # A malformed/unusually long Commons filename (heavy percent-encoding
        # of non-ASCII characters) shouldn't crash a whole sync pass  just
        # skip that one image, same "log and continue" policy as everything
        # else in this module.
        print(f"[manager] skipping oversized image URL for {type_key}#{object_id} ({len(url)} chars)")
        return
    content_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    HardwareDeviceImage.objects.get_or_create(
        type_key=type_key,
        object_id=object_id,
        content_hash=content_hash,
        defaults={
            "image_type": "main",
            "url": url,
            "source_name": LIVE_PROVIDERS[provider_key].name if provider_key in LIVE_PROVIDERS else provider_key,
            "source_url": source_url or "",
            "license_name": "CC0 (Wikidata/Wikimedia Commons)" if provider_key == "wikidata" else "",
            "credit_name": "Wikimedia Commons" if provider_key == "wikidata" else "",
            "credit_url": "https://commons.wikimedia.org/" if provider_key == "wikidata" else "",
        },
    )


def sync_type(type_key):
    """Run one sync pass for a single type_key. Returns a summary dict for
    the management command / tests to report on."""
    model = MODELS_BY_TYPE[type_key]
    field_names = list(FIELD_PRIORITY.get(type_key, {}).keys())
    merged = _merge_provider_records(type_key)

    created, updated, unchanged, profiles_regenerated = 0, 0, 0, 0

    for name_key, provider_records in merged.items():
        row = _find_existing_row(model, provider_records)
        is_new = row is None
        if is_new:
            row = model(name=next(iter(provider_records.values()))["name"])

        # Pick a representative external_id (first live provider in priority
        # order for "manufacturer", since every type tracks that field) so a
        # repeated sync of the same device matches by id, not just by name.
        primary_provider_key = next(iter(provider_records.keys()))
        primary_rec = provider_records[primary_provider_key]
        if not row.external_id and primary_rec.get("external_id"):
            row.external_id = primary_rec["external_id"]
        if primary_rec.get("manufacturer") and not row.manufacturer:
            row.manufacturer = primary_rec["manufacturer"]

        if is_new:
            # Save immediately to get a real pk  HardwareFieldSource rows
            # below need one, and object_id=0 would be ambiguous across
            # devices being created in the same sync pass.
            row.save()

        model_field_names = {f.name for f in model._meta.fields}
        changed_fields = []
        for field_name in field_names:
            if field_name not in model_field_names:
                continue  # "image"/"benchmarks" etc. aren't real model columns
            provider_key, new_value = _resolve_field(type_key, field_name, provider_records)
            if new_value is None:
                continue
            old_value = getattr(row, field_name, None)
            if str(old_value) != str(new_value):
                setattr(row, field_name, new_value)
                changed_fields.append((field_name, old_value, new_value, provider_key))
            # Provenance is recorded regardless of whether the value changed
            # this round  it's "who supplied this field as of now", not a
            # change log (HardwareSpecChange is the change log).
            HardwareFieldSource.objects.update_or_create(
                type_key=type_key, object_id=row.pk, field_name=field_name,
                defaults={
                    "provider_key": provider_key or "manual",
                    "raw_value": str(new_value),
                    "source_url": provider_records.get(provider_key, {}).get("source_url", "") if provider_key else "",
                },
            )

        row.last_synced_at = timezone.now()
        row.save()

        for field_name, old_value, new_value, provider_key in changed_fields:
            HardwareSpecChange.objects.create(
                type_key=type_key, object_id=row.pk, field=field_name,
                old_value=None if is_new else (str(old_value) if old_value is not None else None),
                new_value=str(new_value),
                source_url=provider_records.get(provider_key, {}).get("source_url", "") if provider_key else "",
            )

        image_provider_key, image_url = _resolve_field(type_key, "image", {
            k: {"image": v.get("image_url"), "source_url": v.get("source_url")} for k, v in provider_records.items()
        })
        if image_url:
            _record_image(type_key, row.pk, image_url, provider_records[image_provider_key].get("source_url"), image_provider_key)

        if is_new:
            created += 1
        elif changed_fields:
            updated += 1
        else:
            unchanged += 1

        if is_new or changed_fields:
            profile = ai_knowledge.generate_profile(row, type_key)
            if profile is not None:
                profiles_regenerated += 1

    return {
        "type_key": type_key,
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "profiles_regenerated": profiles_regenerated,
        "devices_seen": len(merged),
    }
