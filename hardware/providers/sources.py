"""Real publications wired into the hardware ingestion pipeline, per the
user's own source list. Every feed URL below was verified live (real
feedparser.parse() call against the actual URL, from this backend, not
just a plan-time guess) before being registered.

Not included, despite being on the original list:
- IGN  feeds.ign.com/ign/games-all does 200 now (302 redirect to
  ign.com/rss/articles/feed?tags=games), but only ~1/20 entries are
  hardware-relevant (mostly reviews/industry drama), so it's not worth
  wiring in for hardware coverage. Re-verified 2026-08-04.
- VideoCardz  the feed URL is real, but the site is behind Cloudflare bot
  protection that returns a 403 "Attention Required" challenge page to
  both a generic fetch and this backend's own feedparser call (confirmed
  directly, not assumed). This isn't a code bug to work around  bypassing
  Cloudflare's bot challenge would cross into scraping-evasion territory
  this project avoids elsewhere. `videocardz` below is left defined (in
  case a future official RSS/API access path appears) but deliberately
  NOT added to ALL_SOURCES. GPU coverage still exists via Tom's Hardware
  and TechPowerUp, both of which already classify real GPU stories.

Each entry below is a plain RSSFeedProvider instance  see rss_provider.py
for the shared fetch/classify logic. Category keyword lists are
hand-curated (same spirit as news/services.py's CATEGORY_KEYWORDS), scoped
to only the categories each publication plausibly covers.
"""
from .rss_provider import RSSFeedProvider

toms_hardware = RSSFeedProvider(
    name="Tom's Hardware",
    feed_url="https://www.tomshardware.com/feeds/all",
    category_keywords={
        "cpus": ["cpu", "processor", "ryzen", "core i", "threadripper", "epyc", "intel core"],
        "gpus": ["gpu", "graphics card", "radeon", "geforce", "rtx ", "rx 7", "rx 9"],
        "motherboards": ["motherboard", "mobo", "chipset", "socket am5", "socket lga"],
        "cooling": ["cooler", "cooling", "aio", "liquid cooling", "heatsink", "case fan"],
        "pc_building": ["pc build", "build guide", "assembling a pc", "how to build a pc"],
        "buying_guides": [
            "buying guide", "buyer's guide", "best gaming", "best cpus", "best gpus",
            "best laptops", "best ssd", "tech deals", "best budget",
        ],
    },
)

techpowerup = RSSFeedProvider(
    name="TechPowerUp",
    feed_url="https://www.techpowerup.com/rss/news",
    category_keywords={
        "cpus": ["cpu", "processor", "ryzen", "core i", "threadripper", "epyc", "intel core"],
        "gpus": ["gpu", "graphics card", "radeon", "geforce", "rtx ", "rx 7", "rx 9"],
        "ram": ["ram ", "memory kit", "ddr5", "ddr4"],
        "storage": ["ssd", "nvme", "hard drive", "hdd", "storage"],
        "monitors": ["monitor", "display panel", "refresh rate", "oled panel"],
    },
)

videocardz = RSSFeedProvider(
    name="VideoCardz",
    feed_url="https://videocardz.com/rss",
    single_category="gpus",  # GPU news exclusively, per the source's own focus
)

gsmarena = RSSFeedProvider(
    name="GSMArena",
    feed_url="https://www.gsmarena.com/rss-news-reviews.php3",
    category_keywords={
        "smartphones": ["phone", "smartphone", "galaxy", "pixel", "iphone", "oneplus", "xiaomi", "vivo"],
        "mobile_socs": ["snapdragon", "dimensity", "exynos", "bionic", "tensor", "soc "],
    },
)

pc_gamer = RSSFeedProvider(
    name="PC Gamer",
    feed_url="https://www.pcgamer.com/rss/",
    category_keywords={
        "gaming": ["game", "gaming", "steam", "xbox", "playstation", "esports"],
        "gaming_laptops": ["gaming laptop"],
        "desktop_pcs": ["prebuilt", "desktop pc", "gaming pc"],
    },
)

rock_paper_shotgun = RSSFeedProvider(
    name="Rock Paper Shotgun",
    feed_url="https://www.rockpapershotgun.com/feed",
    category_keywords={
        "gaming": ["game", "gaming", "steam", "xbox", "playstation", "esports", "mod"],
        "gaming_laptops": ["gaming laptop", "steam deck", "handheld"],
        "gpus": ["gpu", "graphics card", "radeon", "geforce", "rtx "],
        "cpus": ["cpu", "processor", "ryzen", "core i"],
        "desktop_pcs": ["prebuilt", "desktop pc", "gaming pc", "pc build"],
    },
)

ALL_SOURCES = [toms_hardware, techpowerup, gsmarena, pc_gamer, rock_paper_shotgun]
