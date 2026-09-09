"""Per-device image lookup  the analogue of core.category_images.get_article_image
but for a specific CPU/GPU/Laptop/MobileSoC row rather than a category pool.
Priority order: an admin-uploaded override always wins over a same-image_type
provider-sourced row; a device with zero HardwareDeviceImage rows at all
falls back to the existing category-level CategoryImage pool (unchanged
behavior for anything not yet touched by a provider sync)."""
import hashlib

from django.core.cache import cache

from core.category_images import get_article_image

from .models import HardwareDeviceImage

# Mirrors HardwareArticle's own category choices closely enough to reuse the
# same category-image pool as a last-resort fallback.
_CATEGORY_FALLBACK = {
    "cpu": "cpus",
    "gpu": "gpus",
    "laptop": "gaming_laptops",
    "mobile_soc": "mobile_socs",
}


_TYPE_LABEL = {"cpu": "CPU processor", "gpu": "graphics card", "laptop": "laptop", "mobile_soc": "smartphone chip"}


def ensure_device_image(device, type_key):
    """Lazily fetch a real image for a device that has none, via the Intelligent
    pipeline (device name + manufacturer). Stores a HardwareDeviceImage row on a
    hit so it's a one-time cost per device; a cache marker suppresses repeated
    live attempts on a miss. Best-effort  never raises, never blocks on failure.
    Returns True if a new image was stored.

    Kept separate from the provider spec-sync (which pulls Wikidata P18 where it
    exists): this fills the gaps Wikidata doesn't cover, using the same honest
    Commons/Google retrieval as the article pipeline."""
    if HardwareDeviceImage.objects.filter(type_key=type_key, object_id=device.pk).exists():
        return False
    marker = f"intel_devimg_tried:{type_key}:{device.pk}"
    if cache.get(marker):
        return False
    cache.set(marker, 1, timeout=60 * 60 * 24)  # don't re-attempt a miss for a day

    from core.intel import pipeline

    name = getattr(device, "name", "") or str(device)
    manufacturer = getattr(device, "manufacturer", "") or ""
    title = f"{manufacturer} {name}".strip()
    try:
        result = pipeline.resolve_article_image(title, _TYPE_LABEL.get(type_key, ""), type_key)
    except Exception:  # noqa: BLE001
        result = None
    if not result:
        return False

    url = result["image_url"]
    HardwareDeviceImage.objects.get_or_create(
        type_key=type_key,
        object_id=device.pk,
        content_hash=hashlib.sha256(url.encode("utf-8")).hexdigest(),
        defaults={
            "image_type": "main",
            "url": url,
            "source_name": result.get("source_name", ""),
            "source_url": result.get("source_url", ""),
            "license_name": result.get("license_name", ""),
            "credit_name": result.get("credit_name", ""),
            "credit_url": result.get("credit_url", ""),
            "is_admin_override": False,
        },
    )
    return True


def get_device_images(type_key, object_id):
    """Returns a list of image dicts for one device, ordered main-first, with
    is_admin_override rows taking priority over a provider row of the same
    image_type. Empty list (not a fabricated fallback image) if the device
    has no HardwareDeviceImage rows at all and the category pool is empty too."""
    rows = list(
        HardwareDeviceImage.objects.filter(type_key=type_key, object_id=object_id).order_by(
            "-is_admin_override", "image_type"
        )
    )
    if not rows:
        category = _CATEGORY_FALLBACK.get(type_key)
        fallback = get_article_image("hardware", category, object_id) if category else None
        if not fallback:
            return []
        return [
            {
                "image_type": "main",
                "url": fallback["thumb_url"] or fallback["image_url"],
                "credit_name": fallback["credit_name"],
                "credit_url": fallback["credit_url"],
                "license_name": fallback["license_name"],
                "is_category_fallback": True,
            }
        ]

    by_type = {}
    for row in rows:
        by_type.setdefault(row.image_type, row)  # first wins: override sorted first

    return [
        {
            "image_type": row.image_type,
            "url": row.url,
            "credit_name": row.credit_name,
            "credit_url": row.credit_url,
            "license_name": row.license_name,
            "is_admin_override": row.is_admin_override,
        }
        for row in by_type.values()
    ]
