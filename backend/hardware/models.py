from django.db import models
from django.utils import timezone

from core.intel.models_mixin import IntelImageMixin

# ----------------------------------------------------------------- categories

# The 14 categories from the Hardware & Gaming Intelligence Platform spec.
# Lives as plain choices on HardwareArticle  same pattern as
# news.NewsDraft.CATEGORY_CHOICES, not a separate lookup table, so adding a
# 15th category later is a one-line change, not a migration-plus-seed-data
# exercise.
CATEGORY_CHOICES = [
    ("cpus", "CPUs"),
    ("gpus", "GPUs"),
    ("gaming", "Gaming"),
    ("gaming_laptops", "Gaming Laptops"),
    ("desktop_pcs", "Desktop PCs"),
    ("smartphones", "Smartphones"),
    ("mobile_socs", "Mobile SoCs"),
    ("monitors", "Monitors"),
    ("storage", "Storage (SSD/HDD)"),
    ("ram", "RAM"),
    ("motherboards", "Motherboards"),
    ("cooling", "Cooling"),
    ("pc_building", "PC Building"),
    ("buying_guides", "Hardware Buying Guides"),
]


# --------------------------------------------------------------- spec models
# Reference data for comparison pages and buying guides  populated through
# Django's built-in /admin/ today (see hardware/admin.py), the same starting
# point news.NewsDraft moderation had before it got a cockpit tab. A future
# ingestion provider (hardware/providers/) would create/update these same
# rows instead of a human doing it by hand.


class CPU(models.Model):
    name = models.CharField(max_length=150)
    manufacturer = models.CharField(max_length=80)
    generation = models.CharField(max_length=80, blank=True)
    architecture = models.CharField(max_length=80, blank=True)
    socket = models.CharField(max_length=50, blank=True)
    cores = models.PositiveSmallIntegerField(null=True, blank=True)
    threads = models.PositiveSmallIntegerField(null=True, blank=True)
    cache_mb = models.FloatField(null=True, blank=True, help_text="Total cache, MB")
    base_clock_ghz = models.FloatField(null=True, blank=True)
    boost_clock_ghz = models.FloatField(null=True, blank=True)
    tdp_watts = models.PositiveSmallIntegerField(null=True, blank=True)
    process_node_nm = models.PositiveSmallIntegerField(null=True, blank=True)
    release_date = models.DateField(null=True, blank=True)

    # --------------------------------------------------------- provider sync
    # See hardware/providers/ (spec_base.py, wikidata_provider.py, manager.py).
    # external_id null => fully hand-curated row; non-null => at least one
    # provider (today: Wikidata) contributed. performance_score/value_score
    # are curation fields a provider sync must NEVER write  no live source
    # supplies CoreRipper's own buyer-facing score, so these stay null until
    # an admin sets them.
    external_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    performance_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="CoreRipper curated 0-100 score, not provider-sourced")
    value_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="CoreRipper curated 0-100 score, not provider-sourced")
    efficiency_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="CoreRipper curated 0-100 score, not provider-sourced")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["manufacturer", "name"]

    def __str__(self):
        return self.name


class GPU(models.Model):
    name = models.CharField(max_length=150)
    manufacturer = models.CharField(max_length=80)
    vram_gb = models.FloatField(null=True, blank=True)
    cuda_or_stream_cores = models.PositiveIntegerField(
        null=True, blank=True, help_text="CUDA cores (NVIDIA) or Stream Processors (AMD)"
    )
    ray_tracing = models.BooleanField(default=False)
    power_draw_watts = models.PositiveSmallIntegerField(null=True, blank=True)
    recommended_psu_watts = models.PositiveSmallIntegerField(null=True, blank=True)
    display_outputs = models.CharField(max_length=200, blank=True, help_text="e.g. '3x DisplayPort 2.1, 1x HDMI 2.1'")
    release_date = models.DateField(null=True, blank=True)

    external_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    performance_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="CoreRipper curated 0-100 score, not provider-sourced")
    value_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="CoreRipper curated 0-100 score, not provider-sourced")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["manufacturer", "name"]

    def __str__(self):
        return self.name


class MobileSoC(models.Model):
    name = models.CharField(max_length=150)
    manufacturer = models.CharField(max_length=80)
    cpu_architecture = models.CharField(max_length=150, blank=True)
    gpu = models.CharField(max_length=150, blank=True, help_text="Integrated GPU name, e.g. 'Adreno 750'")
    ai_engine = models.CharField(max_length=150, blank=True, help_text="e.g. 'Hexagon NPU'")
    fabrication_process_nm = models.PositiveSmallIntegerField(null=True, blank=True)
    supported_phones = models.TextField(blank=True, help_text="Comma-separated or freeform list of known phones")
    release_date = models.DateField(null=True, blank=True)

    external_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    performance_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="CoreRipper curated 0-100 score, not provider-sourced")
    efficiency_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="CoreRipper curated 0-100 score, not provider-sourced")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Mobile SoC"
        ordering = ["manufacturer", "name"]

    def __str__(self):
        return self.name


class Laptop(models.Model):
    name = models.CharField(max_length=150)
    manufacturer = models.CharField(max_length=80)
    cpu = models.ForeignKey(CPU, on_delete=models.SET_NULL, null=True, blank=True, related_name="laptops")
    gpu = models.ForeignKey(GPU, on_delete=models.SET_NULL, null=True, blank=True, related_name="laptops")
    ram_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    storage_gb = models.PositiveIntegerField(null=True, blank=True)
    display = models.CharField(max_length=150, blank=True, help_text="e.g. '16\" 2560x1600 OLED'")
    refresh_rate_hz = models.PositiveSmallIntegerField(null=True, blank=True)
    battery_whr = models.FloatField(null=True, blank=True)
    weight_kg = models.FloatField(null=True, blank=True)
    release_date = models.DateField(null=True, blank=True)

    external_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    performance_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="CoreRipper curated 0-100 score, not provider-sourced")
    portability_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="CoreRipper curated 0-100 score, not provider-sourced")
    value_score = models.PositiveSmallIntegerField(null=True, blank=True, help_text="CoreRipper curated 0-100 score, not provider-sourced")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["manufacturer", "name"]

    def __str__(self):
        return self.name


# ------------------------------------------------------------------- article
# Mirrors news.NewsDraft / ArticleSource / ArticleUpdate's shape (a
# moderation-queue content row + real Sources + a real timeline)  a
# deliberate parallel structure, not a cross-app FK reuse of the news
# models, so this app's migrations never touch the live news tables. See
# project memory for the reasoning: this app being separate from `news`
# mirrors `news` already being separate from `blog`.


class HardwareArticle(IntelImageMixin, models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending Review"),
        ("published", "Published"),
        ("rejected", "Rejected"),
    ]

    title = models.CharField(max_length=300)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)

    ai_summary = models.TextField(blank=True, help_text="Short blurb for card previews / digests")
    ai_draft_body = models.TextField(blank=True, help_text="Full article body")

    # At most one of these is set  which hardware spec row this article is
    # "about", if any (a buying guide or Gaming-category piece may set none).
    cpu = models.ForeignKey(CPU, on_delete=models.SET_NULL, null=True, blank=True, related_name="articles")
    gpu = models.ForeignKey(GPU, on_delete=models.SET_NULL, null=True, blank=True, related_name="articles")
    laptop = models.ForeignKey(Laptop, on_delete=models.SET_NULL, null=True, blank=True, related_name="articles")
    mobile_soc = models.ForeignKey(MobileSoC, on_delete=models.SET_NULL, null=True, blank=True, related_name="articles")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.status}] {self.title}"

    @property
    def computed_reading_time(self):
        from core.reading_time import estimate_reading_minutes

        return estimate_reading_minutes(self.ai_draft_body)

    @property
    def is_human_reviewed(self):
        return self.reviewed_at is not None

    @property
    def last_updated_at(self):
        latest = self.updates.order_by("-created_at").first()
        return latest.created_at if latest else self.published_at

    @property
    def primary_subject(self):
        """Whichever spec row (if any) this article is about."""
        return self.cpu or self.gpu or self.laptop or self.mobile_soc

    def publish(self):
        first_publish = self.published_at is None
        self.status = "published"
        self.reviewed_at = timezone.now()
        if first_publish:
            self.published_at = self.reviewed_at
        self.save()
        if first_publish:
            self.updates.create(kind="published", title="Article published")

    def reject(self):
        self.status = "rejected"
        self.reviewed_at = timezone.now()
        self.save()


class HardwareArticleSource(models.Model):
    article = models.ForeignKey(HardwareArticle, on_delete=models.CASCADE, related_name="sources")
    url = models.URLField(max_length=500)
    name = models.CharField(max_length=150)
    is_primary = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.name} ({self.article_id})"


class HardwareArticleUpdate(models.Model):
    KIND_CHOICES = [
        ("published", "Published"),
        ("update", "Content Update"),
        ("correction", "Correction"),
        ("advisory", "Advisory / Release Note"),
    ]

    article = models.ForeignKey(HardwareArticle, on_delete=models.CASCADE, related_name="updates")
    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="update")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.kind}] {self.title}"


# --------------------------------------------------------- provider pipeline
# Everything below supports hardware/providers/ (the multi-provider spec
# sync pipeline)  see that package's docstrings for the fetch/merge logic.
# These models use a plain (type_key, object_id) pair rather than a GenericFK
# because there are exactly four possible type_keys (cpu/gpu/laptop/mobile_soc,
# see hardware.spec_fields.TRACKED_SPEC_FIELDS) and a real FK per type would
# mean four near-identical models instead of one.

TYPE_KEY_CHOICES = [
    ("cpu", "CPU"),
    ("gpu", "GPU"),
    ("laptop", "Laptop"),
    ("mobile_soc", "Mobile SoC"),
]


class HardwareFieldSource(models.Model):
    """Provenance ledger: which provider last supplied a given field's value
    for a given device, and when. This is what makes "Display came from
    GSMArena, Battery from Notebookcheck, CPU from Wikidata" a queryable fact
    instead of an assumption once a second live provider exists  today only
    `wikidata` and `manual` ever populate `provider_key`."""

    type_key = models.CharField(max_length=20, choices=TYPE_KEY_CHOICES)
    object_id = models.PositiveIntegerField()
    field_name = models.CharField(max_length=60)
    provider_key = models.CharField(max_length=40)
    raw_value = models.TextField(blank=True)
    source_url = models.URLField(max_length=500, blank=True)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("type_key", "object_id", "field_name")]
        ordering = ["type_key", "object_id", "field_name"]

    def __str__(self):
        return f"{self.type_key}#{self.object_id}.{self.field_name} <- {self.provider_key}"


class HardwareSpecChange(models.Model):
    """One row per field a sync pass actually changed  powers a device
    page's "what changed" history and is the trigger for HardwareAIProfile
    regeneration (see hardware/providers/manager.py). Never written for
    curated fields (scores) or admin image overrides  those are excluded
    from sync entirely, so they can never appear here."""

    type_key = models.CharField(max_length=20, choices=TYPE_KEY_CHOICES)
    object_id = models.PositiveIntegerField()
    field = models.CharField(max_length=60)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    source_url = models.URLField(max_length=500, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.type_key}#{self.object_id}.{self.field}: {self.old_value!r} -> {self.new_value!r}"


class HardwareDeviceImage(models.Model):
    """Per-device image asset  replaces a single image_url field with a
    real multi-image table (main/gallery/front/back/.../logo), matching the
    spec's "Device -> Cover/Gallery/Thumbnail" shape. Only `main`/`logo`/
    occasionally `gallery` are realistically populated today (Wikidata P18
    image + P154 logo); the rest exist so an admin can upload them, or a
    future licensed-image provider can populate them, without another
    migration. No GSMArena/manufacturer-site scraping  same licensing
    reasoning as the spec data itself (see providers/ docstrings). Stores a
    hotlinked URL + credit, same as core.CategoryImage, not downloaded bytes."""

    IMAGE_TYPE_CHOICES = [
        ("main", "Main"),
        ("gallery", "Gallery"),
        ("front", "Front"),
        ("back", "Back"),
        ("side", "Side"),
        ("keyboard", "Keyboard"),
        ("ports", "Ports"),
        ("motherboard", "Motherboard"),
        ("packaging", "Packaging"),
        ("thumbnail", "Thumbnail"),
        ("logo", "Manufacturer Logo"),
    ]

    type_key = models.CharField(max_length=20, choices=TYPE_KEY_CHOICES)
    object_id = models.PositiveIntegerField()
    image_type = models.CharField(max_length=20, choices=IMAGE_TYPE_CHOICES, default="main")
    url = models.URLField(max_length=1000)
    source_name = models.CharField(max_length=100, blank=True, help_text="e.g. 'Wikimedia Commons'")
    source_url = models.URLField(max_length=500, blank=True)
    license_name = models.CharField(max_length=100, blank=True)
    resolution = models.CharField(max_length=20, blank=True, help_text="e.g. '1920x1080'")
    content_hash = models.CharField(max_length=64, db_index=True, help_text="sha256 of the URL  dedupe key, prevents re-syncing the same image twice")
    credit_name = models.CharField(max_length=150, blank=True)
    credit_url = models.URLField(max_length=500, blank=True)
    is_admin_override = models.BooleanField(default=False, help_text="True for an admin-uploaded image; always wins over a provider-sourced one of the same image_type")
    last_checked_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("type_key", "object_id", "content_hash")]
        ordering = ["type_key", "object_id", "image_type"]

    def __str__(self):
        return f"{self.type_key}#{self.object_id} [{self.image_type}]"


class HardwareAIProfile(models.Model):
    """The 'AI Knowledge' layer  structured buyer-facing knowledge about a
    device (who it's for, its tradeoffs, expected lifespan). One profile per
    device, regenerated only when the specs it was built from actually
    change (source_spec_hash mismatch), never on a timer. status defaults to
    "published" because human review is optional per spec  a superuser can
    flip a specific profile to "draft" to hide it while editing, mirroring
    HardwareArticle's publish()/reject() shape without the public-facing
    timeline (a profile isn't a moderation queue item the way an ingested
    article is)."""

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("reviewed", "Reviewed"),
        ("published", "Published"),
    ]

    type_key = models.CharField(max_length=20, choices=TYPE_KEY_CHOICES)
    object_id = models.PositiveIntegerField()

    best_for = models.JSONField(default=list, blank=True, help_text='e.g. ["Students", "Programming", "Office"]')
    strengths = models.JSONField(default=list, blank=True)
    trade_offs = models.JSONField(default=list, blank=True)
    expected_lifespan_years = models.CharField(max_length=60, blank=True, help_text="e.g. '5+ years'")
    recommended_ram_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    recommended_ssd_gb = models.PositiveSmallIntegerField(null=True, blank=True)
    verdict_text = models.TextField(blank=True, help_text="Short prose summary shown on device pages")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="published")
    source_spec_hash = models.CharField(max_length=64, blank=True, help_text="sha256 of the tracked spec fields this profile was generated from")
    generated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("type_key", "object_id")]

    def __str__(self):
        return f"AI profile: {self.type_key}#{self.object_id} [{self.status}]"
