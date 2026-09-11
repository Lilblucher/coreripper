import time

from django.core.management.base import BaseCommand

from core.commons_images import fetch_commons_images
from core.models import CategoryImage

POOL_SIZE = 4

# Hand-curated search terms per category, same spirit as the frontend's own
# hand-curated per-category icon/color maps (news.html / hardware.html) 
# not derived from article titles, since AI-drafted titles are too varied
# to reliably map to a good Commons search term.
NEWS_SEARCH_TERMS = {
    "networking": "computer network server room",
    "security": "padlock security",
    "dev": "software developer programming code",
    "ai": "artificial intelligence technology",
    "databases": "data center server room",
    "linux": "linux operating system computer",
}

HARDWARE_SEARCH_TERMS = {
    "cpus": "computer processor CPU chip",
    "gpus": "graphics card GPU",
    "gaming": "gaming PC setup",
    # NOT "gaming laptop computer"  every result Commons returned was a
    # desktop-tower build (one project's "Astaroth" build-log photos, RGB
    # case interior included) with zero actual laptops among them. Dropping
    # the generic "computer" term and leading with "notebook" (the more
    # Commons-catalogued synonym for a laptop) keeps the match on the right
    # form factor.
    "gaming_laptops": "gaming laptop notebook",
    # NOT "desktop computer tower"  same disambiguation bug as mobile_socs'
    # old term: "tower" alone matched an actual stone tower building
    # (Broadway Tower). "case" is an unambiguous PC-hardware noun.
    "desktop_pcs": "desktop computer case",
    "smartphones": "smartphone mobile phone",
    # NOT "mobile phone chip"  Commons full-text search has no way to
    # disambiguate "silicon chip" from "food chip"/"payment chip", and that
    # term matched banana chips, a chip-and-pin terminal, and a "fish 'n'
    # chips" pub sign (all real, freely-licensed, and completely wrong).
    # "silicon die" is unambiguous camera-vocabulary for a bare chip photo.
    "mobile_socs": "semiconductor silicon die integrated circuit",
    # NOT "computer monitor display"  matched a candid photo of a cat
    # looking at its own reflection in a monitor. "LCD computer monitor
    # screen product" (tried next) was worse still, matching a train
    # platform photo and a church via unrelated tags. "widescreen" is what
    # actually anchored the match to real monitor product photos.
    "monitors": "computer monitor LCD widescreen",
    "storage": "hard drive SSD storage",
    "ram": "computer memory RAM module",
    # NOT "computer motherboard circuit board" (nor the "ATX computer
    # motherboard circuit board" / "motherboard mainboard PCB computer"
    # variants tried after it)  every broader phrasing kept resurfacing a
    # round smart-speaker (Amazon Echo Dot) PCB, a real motherboard-shaped
    # board but the wrong device class entirely. This narrower term is the
    # one that stopped matching it.
    "motherboards": "ATX PC motherboard mainboard",
    "cooling": "PC cooling fan heatsink",
    "pc_building": "PC building computer case",
    "buying_guides": "computer store electronics shopping",
}


class Command(BaseCommand):
    help = (
        "Fetches real, freely-licensed photos from Wikimedia Commons for each "
        "news/hardware category and stores them in core.CategoryImage. "
        "Idempotent  skips any (app, category) that already has a full pool, "
        "so re-running doesn't re-hit the Commons API for nothing."
    )

    def handle(self, *args, **options):
        for app, terms in (("news", NEWS_SEARCH_TERMS), ("hardware", HARDWARE_SEARCH_TERMS)):
            for category, term in terms.items():
                existing = CategoryImage.objects.filter(app=app, category=category).count()
                if existing >= POOL_SIZE:
                    self.stdout.write(f"{app}/{category}: already has {existing}, skipping")
                    continue

                results = fetch_commons_images(term, limit=POOL_SIZE)
                if not results:
                    # Wikimedia's search API can transiently rate-limit rapid
                    # back-to-back requests with an empty result rather than
                    # an HTTP error  one retry after a short pause catches
                    # that case instead of wrongly recording a real gap.
                    time.sleep(2)
                    results = fetch_commons_images(term, limit=POOL_SIZE)
                created = 0
                for r in results:
                    _, was_created = CategoryImage.objects.get_or_create(
                        app=app, category=category, image_url=r["image_url"],
                        defaults={
                            "thumb_url": r["thumb_url"],
                            "credit_name": r["credit_name"],
                            "credit_url": r["credit_url"],
                            "license_name": r["license_name"],
                        },
                    )
                    created += int(was_created)

                if results:
                    self.stdout.write(self.style.SUCCESS(
                        f"{app}/{category}: fetched {len(results)}, created {created}"
                    ))
                else:
                    self.stdout.write(self.style.WARNING(
                        f"{app}/{category}: no Commons results for '{term}'  pool stays empty, "
                        f"frontend will fall back to its category icon"
                    ))
                time.sleep(1)
