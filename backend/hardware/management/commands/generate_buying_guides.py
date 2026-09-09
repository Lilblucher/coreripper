"""management/commands/generate_buying_guides.py

Generates AI-drafted buying guide articles for hardware categories that RSS
ingestion never feeds well (buying_guides, cooling, pc_building, motherboards,
etc.). Uses the same run_ai(user=None) free-model path as news.services
generate_ai_draft — never bills a customer wallet.

Each generated article lands as status="pending" in the Engine Room's Hardware
tab, same moderation gate as every other content type. Nothing goes public until
a human reviews and publishes it.

Usage:
    # Dry-run: show what would be generated, create nothing
    python manage.py generate_buying_guides --dry-run

    # Generate one guide per thin category (< 3 published articles)
    python manage.py generate_buying_guides

    # Force-generate for specific categories regardless of existing count
    python manage.py generate_buying_guides --categories buying_guides cooling

    # Control how many guides per category (default 1)
    python manage.py generate_buying_guides --per-category 2

Target audience context: African students on tight budgets, specifically
Zambia + neighbouring countries. The research data baked into GUIDE_TOPICS
reflects real Zambian market prices and availability (HP EliteBook / Dell
Latitude / Lenovo ThinkPad used-business-laptop segment).
"""
import json
import re

from django.core.management.base import BaseCommand

from hardware.models import CATEGORY_CHOICES, HardwareArticle

# ------------------------------------------------------------------ constants

# A category is considered "thin" if it has fewer than this many published
# articles. Thin categories are the ones we generate for by default.
THIN_THRESHOLD = 3

# Categories the RSS pipeline can actually cover from Tom's Hardware /
# TechPowerUp / PC Gamer — skip these so we don't duplicate their work.
RSS_FED_CATEGORIES = {"cpus", "gpus", "gaming", "gaming_laptops", "smartphones", "mobile_socs", "monitors"}

# ---------------------------------------------------------------------------
# Topic definitions: one or more guide prompts per category.
# Each entry is a dict with:
#   title        – the HardwareArticle.title to create
#   category     – must be a valid CATEGORY_CHOICES key
#   audience     – injected into the AI prompt so the tone is right
#   context      – market-specific facts the AI should weave in
#   angle        – the specific question or framing the guide should answer
# ---------------------------------------------------------------------------
GUIDE_TOPICS = [
    # ---------------------------------------------------------------- buying guides
    {
        "title": "Best Budget Laptops for African Students in 2025: HP EliteBook, Dell Latitude & Lenovo ThinkPad Compared",
        "category": "buying_guides",
        "audience": "university students in Zambia and neighbouring African countries buying their first or second laptop on a tight budget",
        "context": (
            "The Zambian used-laptop market is dominated by refurbished business laptops. "
            "HP EliteBook and ProBook models sell for roughly ZMW 3,800–ZMW 12,000. "
            "Dell Latitude models (especially the 5xxx series) sell for ZMW 1,600–ZMW 10,000. "
            "Lenovo ThinkPads (T-series, X-series) sell for ZMW 2,500–ZMW 13,000. "
            "The sweet spot for most students is a Core i5, 8 GB RAM, 256 GB SSD machine "
            "in the ZMW 3,500–ZMW 7,000 range. Facebook Marketplace is the primary second-hand channel. "
            "Power cuts are common, so battery life matters enormously. "
            "Most students run Windows 10/11 and need Office-compatible software."
        ),
        "angle": "Which family gives the best value for a Zambian or southern-African student, what specs to insist on, and what red flags to avoid on Facebook Marketplace?",
    },
    {
        "title": "Used vs New Laptop in Zambia: Is a Refurbished ThinkPad Worth It for University?",
        "category": "buying_guides",
        "audience": "first-year university students in Zambia deciding between a new budget laptop and a refurbished business machine",
        "context": (
            "New entry-level laptops (Lenovo IdeaPad 1 Celeron, HP 240 G10 Core i3) cost ZMW 7,000–ZMW 12,000 in formal retail. "
            "Comparable refurbished business laptops (ThinkPad T460, Dell Latitude 5400, HP EliteBook 840 G5) "
            "with better build quality, keyboards and repairability cost ZMW 3,500–ZMW 7,000 used. "
            "Risks of used: battery wear, BIOS locks, no warranty, misleading specs on Facebook. "
            "Advantages of used: faster CPU, SSD standard, stronger chassis, easier to repair locally."
        ),
        "angle": "A practical decision framework for the student who has ZMW 5,000–ZMW 8,000 and is weighing both options.",
    },
    {
        "title": "What to Check Before Buying a Used Laptop in Zambia: The 10-Point Inspection Checklist",
        "category": "buying_guides",
        "audience": "students and young professionals in Zambia buying from Facebook Marketplace or classified ads",
        "context": (
            "Common problems in the Zambian used-laptop market: "
            "sellers omit the processor generation (e.g. 6th vs 11th gen makes a huge difference), "
            "battery health is rarely disclosed, HDD vs SSD is sometimes misrepresented, "
            "BIOS/corporate passwords lock machines bought from large-company lease returns, "
            "screens have dead pixels or backlight bleed, chargers are missing or incompatible, "
            "Windows is unactivated. "
            "Prices are often listed in ZMW but some sellers quote USD."
        ),
        "angle": "A step-by-step in-person inspection checklist a student can run through before handing over any money.",
    },
    # ---------------------------------------------------------------- cooling
    {
        "title": "PC Cooling Explained: Air vs Liquid Cooling for African Climates",
        "category": "cooling",
        "audience": "PC builders and gamers in sub-Saharan Africa where ambient temperatures regularly exceed 30 °C",
        "context": (
            "High ambient temperatures in Zambia and surrounding countries mean cooling headroom is tighter than "
            "in Europe or North America where most reviews are written. "
            "Air coolers (Noctua NH-D15, DeepCool AK620, budget Cooler Master options) are reliable, "
            "require no maintenance, and do not leak. "
            "All-in-one liquid coolers (240/280/360 mm radiators) offer lower CPU temps under load "
            "but add pump-failure risk and require good case airflow. "
            "Dust is a significant factor in African environments — filters and regular cleaning matter more here."
        ),
        "angle": "What cooling solution actually makes sense when your room is 32 °C and budget is limited?",
    },
    {
        "title": "Budget CPU Cooler Roundup: Which Aftermarket Cooler Is Worth Fitting on a Student Build?",
        "category": "cooling",
        "audience": "first-time PC builders on a limited budget who want to replace a stock Intel/AMD cooler",
        "context": (
            "Stock coolers (Intel Laminar, AMD Wraith Stealth/Spire) are adequate at stock clocks "
            "but throttle under sustained load or in hot rooms. "
            "A ZMW 500–ZMW 1,500 aftermarket tower cooler (DeepCool GAMMAXX, ID-Cooling SE-224-XT, "
            "Cooler Master Hyper 212) can drop CPU temps 15–20 °C. "
            "Socket compatibility (LGA1700, AM4, AM5) must be checked before buying."
        ),
        "angle": "The cheapest meaningful upgrade a budget builder can make and how to verify compatibility.",
    },
    # ---------------------------------------------------------------- pc_building
    {
        "title": "How to Build a Student PC in Zambia for Under ZMW 10,000",
        "category": "pc_building",
        "audience": "Zambian students and young professionals who want a desktop for study, programming or light gaming",
        "context": (
            "Component availability in Zambia is limited — most parts must be imported or sourced from "
            "South Africa (Takealot) or regional suppliers. "
            "Ryzen 5 5600 + B550 board is a strong value platform in 2025. "
            "RAM prices: 16 GB DDR4 kit is approximately USD 20–30 internationally. "
            "Power supply reliability is critical because load-shedding causes power surges — "
            "a good surge protector or UPS is a worthwhile extra. "
            "Second-hand GPUs (GTX 1660 Super, RX 580) can substitute for new cards when budget is tight."
        ),
        "angle": "A realistic, priced parts list with local sourcing tips and the pitfalls to avoid.",
    },
    {
        "title": "PC Building for Beginners: From Zero to POST in an Afternoon",
        "category": "pc_building",
        "audience": "complete beginners in Africa who have never assembled a PC before",
        "context": (
            "Many first-time builders in the region rely on YouTube tutorials filmed in the US/Europe, "
            "which assume tools, anti-static mats and part availability that may not exist locally. "
            "Common first-build mistakes: forgetting the standoff screws, plugging in the 8-pin EPS "
            "instead of the 24-pin ATX first, missing the front-panel header order, "
            "not seating RAM all the way, thermal paste overapplication."
        ),
        "angle": "A calm, step-by-step first-build walkthrough written for someone who has never held a screwdriver.",
    },
    # ---------------------------------------------------------------- motherboards
    {
        "title": "Motherboard Buying Guide 2025: What Actually Matters for a Budget AMD or Intel Build",
        "category": "motherboards",
        "audience": "first-time PC builders who find motherboard spec sheets confusing",
        "context": (
            "Common confusion points: chipset tiers (B650 vs X670, B760 vs Z790), "
            "VRM quality (matters for Ryzen 7/9 and Core i7/i9, irrelevant for Ryzen 5/Core i5 at stock), "
            "DDR4 vs DDR5 platform choice, M.2 slot count and keying (M-key NVMe vs B+M SATA), "
            "PCIe gen 4 vs gen 5 (no practical gaming difference today), "
            "form factor (ATX/mATX/ITX) matching to case size."
        ),
        "angle": "Strip away the marketing and explain what a budget builder actually needs to check before buying a board.",
    },
    # ---------------------------------------------------------------- storage
    {
        "title": "SSD vs HDD in 2025: Should You Still Buy a Hard Drive?",
        "category": "storage",
        "audience": "laptop and desktop buyers in Africa who are often offered HDD machines to save cost",
        "context": (
            "In Zambia and the wider region, refurbished laptops with HDDs are still widely sold. "
            "A 256 GB SSD boot drive makes a bigger real-world speed difference than a CPU upgrade "
            "for most student/office workloads. "
            "NVMe SSDs (Samsung 980, Kingston NV3, WD Green SN350) are available internationally "
            "from USD 20–35. SATA SSDs are a reasonable upgrade path for machines that lack M.2. "
            "HDDs still make sense for bulk media/backup storage where ZMW/GB matters more than speed."
        ),
        "angle": "A practical answer to 'should I pay more for SSD or just get a bigger HDD?'",
    },
    # ---------------------------------------------------------------- ram
    {
        "title": "How Much RAM Do You Actually Need? A No-Nonsense Guide for Students and Developers",
        "category": "ram",
        "audience": "students and junior developers in Africa deciding between 8 GB and 16 GB when buying or upgrading",
        "context": (
            "8 GB DDR4 is the baseline in the Zambian used-laptop market. "
            "16 GB matters for: running a local dev environment (Node/Django + Postgres + browser), "
            "video editing, running a VM, or heavy browser tab usage. "
            "32 GB is overkill for most students. "
            "Single-channel (1 × 8 GB) vs dual-channel (2 × 4 GB or 2 × 8 GB) makes a measurable "
            "difference on integrated graphics (AMD APU / Intel Iris Xe)."
        ),
        "angle": "When is paying for more RAM actually worth it vs when is it marketing noise?",
    },
]

# ---------------------------------------------------------------------------
# AI prompt builder
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a hardware journalist writing for CoreRipper, a developer and tech knowledge hub "
    "with a large African student audience. "
    "You write practical, honest buying guides grounded in real market conditions. "
    "You never fabricate prices, product names, or benchmark numbers. "
    "You write in plain English — no jargon without explanation. "
    "You never use filler phrases like 'in conclusion', 'to summarize', or 'in this article we will'. "
    "Your tone is direct and friendly, like a knowledgeable older student helping a younger one."
)


def _build_user_prompt(topic):
    return f"""Write a detailed buying guide article for CoreRipper's hardware section.

Title: {topic['title']}
Category: {topic['category']}
Target audience: {topic['audience']}

Market context to weave in (use this to ground your advice in real local conditions):
{topic['context']}

Central question this guide must answer:
{topic['angle']}

Requirements:
- Output ONLY a JSON object with two keys: "summary" and "body".
- "summary": 2-3 sentences suitable for a card preview / digest email. Must stand alone.
- "body": the full article as flowing prose. Use markdown headings (##, ###) to organise sections.
  Minimum 5 sections, minimum 600 words total. Sections should include:
  - An opening that frames the problem for the specific audience
  - The core recommendation(s) with reasoning
  - Specific models, specs, or price ranges grounded in the market context given
  - A "what to watch out for" or red-flags section
  - A brief bottom-line recommendation
- Do NOT fabricate benchmark scores or specific test results.
- Do NOT reproduce copyrighted text from other publications.
- Write entirely in your own words.

Respond with ONLY the JSON object, no markdown fences, no preamble."""


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = (
        "Generate AI-drafted buying guide articles for thin/empty hardware categories. "
        "Everything lands as status='pending' for Engine Room review."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be generated without creating any DB rows.",
        )
        parser.add_argument(
            "--categories",
            nargs="+",
            metavar="CATEGORY",
            help=(
                "Only generate guides for these category keys. "
                "Valid values: " + ", ".join(k for k, _ in CATEGORY_CHOICES)
            ),
        )
        parser.add_argument(
            "--per-category",
            type=int,
            default=1,
            metavar="N",
            help="Maximum number of guides to generate per category (default: 1).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Generate even for categories that already have enough published articles.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        per_category = options["per_category"]
        target_categories = set(options["categories"]) if options["categories"] else None

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing will be written to the database.\n"))

        # Build a set of categories that need content.
        thin_categories = self._find_thin_categories(force)

        # Filter to what the user requested (if anything).
        topics_to_run = []
        category_counts = {}  # how many we've queued per category this run

        for topic in GUIDE_TOPICS:
            cat = topic["category"]

            # Skip if the user restricted to specific categories and this isn't one.
            if target_categories and cat not in target_categories:
                continue

            # Skip if category is already well-fed and we're not forcing.
            if not force and cat not in thin_categories:
                self.stdout.write(f"  SKIP  [{cat}] already has enough published articles.")
                continue

            # Respect per-category cap.
            category_counts[cat] = category_counts.get(cat, 0)
            if category_counts[cat] >= per_category:
                continue

            # Skip if an article with the exact same title already exists (idempotent).
            if HardwareArticle.objects.filter(title=topic["title"]).exists():
                self.stdout.write(f"  SKIP  [{cat}] already exists: {topic['title']}")
                continue

            topics_to_run.append(topic)
            category_counts[cat] += 1

        if not topics_to_run:
            self.stdout.write(self.style.SUCCESS("Nothing to generate — all categories are well-fed."))
            return

        self.stdout.write(f"Will generate {len(topics_to_run)} guide(s):\n")
        for t in topics_to_run:
            self.stdout.write(f"  [{t['category']}] {t['title']}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run complete. Re-run without --dry-run to create articles."))
            return

        # Generate.
        created = 0
        failed = 0
        for topic in topics_to_run:
            self.stdout.write(f"\nGenerating: {topic['title'][:70]}...")
            try:
                article = self._generate_and_save(topic)
                self.stdout.write(
                    self.style.SUCCESS(f"  Created HardwareArticle #{article.pk} (status=pending)")
                )
                created += 1
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"  FAILED: {exc}"))
                failed += 1

        self.stdout.write(
            f"\nDone. {created} article(s) created, {failed} failed. "
            "Review them in the Engine Room → Hardware tab."
        )

    # ------------------------------------------------------------------

    def _find_thin_categories(self, force):
        """Return the set of category keys that have fewer than THIN_THRESHOLD
        published articles. RSS-fed categories are always excluded."""
        if force:
            # Return everything (except pure RSS-fed cats unless explicitly asked for).
            return {k for k, _ in CATEGORY_CHOICES} - RSS_FED_CATEGORIES

        from django.db.models import Count, Q
        counts = (
            HardwareArticle.objects
            .filter(status="published")
            .values("category")
            .annotate(n=Count("id"))
        )
        published_counts = {row["category"]: row["n"] for row in counts}

        thin = set()
        for key, _ in CATEGORY_CHOICES:
            if key in RSS_FED_CATEGORIES:
                continue
            if published_counts.get(key, 0) < THIN_THRESHOLD:
                thin.add(key)
        return thin

    def _generate_and_save(self, topic):
        from credits.services import run_ai
        from hardware.models import HardwareArticle

        system = SYSTEM_PROMPT
        user_msg = _build_user_prompt(topic)

        result = run_ai(
            user=None,
            operation="buying_guide_draft",
            system=system,
            user_msg=user_msg,
        )
        content = result["content"].strip()

        # Strip markdown code fences defensively (same pattern as news.services).
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE).strip()

        parsed = json.loads(content)

        def _as_text(val):
            if isinstance(val, list):
                return "\n\n".join(str(p).strip() for p in val if str(p).strip())
            return str(val or "").strip()

        summary = _as_text(parsed.get("summary"))
        body = _as_text(parsed.get("body"))

        if not summary or not body:
            raise ValueError("AI response missing 'summary' or 'body'.")

        article = HardwareArticle.objects.create(
            title=topic["title"],
            category=topic["category"],
            ai_summary=summary,
            ai_draft_body=body,
            # status defaults to "pending" — nothing goes public without review.
        )
        return article
