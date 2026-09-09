from django.contrib import admin

from .models import (
    CPU,
    GPU,
    HardwareAIProfile,
    HardwareArticle,
    HardwareArticleSource,
    HardwareArticleUpdate,
    HardwareDeviceImage,
    HardwareFieldSource,
    HardwareSpecChange,
    Laptop,
    MobileSoC,
)


class HardwareArticleSourceInline(admin.TabularInline):
    model = HardwareArticleSource
    extra = 0


class HardwareArticleUpdateInline(admin.TabularInline):
    model = HardwareArticleUpdate
    extra = 0
    readonly_fields = ["created_at"]


@admin.register(HardwareArticle)
class HardwareArticleAdmin(admin.ModelAdmin):
    """Moderation surface for hardware content  mirrors
    news.admin.NewsDraftAdmin exactly (same publish()/reject() routing so a
    bulk action still stamps published_at + logs a timeline entry per row,
    not a bare queryset.update()). No cockpit tab yet  see hardware/admin_views.py's
    docstring; this is the one moderation UI today."""

    list_display = ["title", "category", "status", "created_at", "published_at"]
    list_filter = ["status", "category"]
    search_fields = ["title"]
    readonly_fields = ["created_at", "reviewed_at", "published_at"]
    actions = ["approve_and_publish", "reject"]
    inlines = [HardwareArticleSourceInline, HardwareArticleUpdateInline]

    def approve_and_publish(self, request, queryset):
        for article in queryset:
            article.publish()
    approve_and_publish.short_description = "Approve and publish selected articles"

    def reject(self, request, queryset):
        for article in queryset:
            article.reject()
    reject.short_description = "Reject selected articles"


def _is_synced(obj):
    return bool(obj.external_id)
_is_synced.short_description = "Provider-synced"
_is_synced.boolean = True


@admin.register(CPU)
class CPUAdmin(admin.ModelAdmin):
    list_display = ["name", "manufacturer", "cores", "threads", "tdp_watts", "release_date",
                     "performance_score", "value_score", "efficiency_score", _is_synced, "last_synced_at"]
    list_filter = ["manufacturer"]
    search_fields = ["name", "manufacturer"]
    readonly_fields = ["external_id", "last_synced_at"]


@admin.register(GPU)
class GPUAdmin(admin.ModelAdmin):
    list_display = ["name", "manufacturer", "vram_gb", "ray_tracing", "power_draw_watts", "release_date",
                     "performance_score", "value_score", _is_synced, "last_synced_at"]
    list_filter = ["manufacturer", "ray_tracing"]
    search_fields = ["name", "manufacturer"]
    readonly_fields = ["external_id", "last_synced_at"]


@admin.register(Laptop)
class LaptopAdmin(admin.ModelAdmin):
    list_display = ["name", "manufacturer", "cpu", "gpu", "ram_gb", "release_date",
                     "performance_score", "portability_score", "value_score", _is_synced, "last_synced_at"]
    list_filter = ["manufacturer"]
    search_fields = ["name", "manufacturer"]
    readonly_fields = ["external_id", "last_synced_at"]


@admin.register(MobileSoC)
class MobileSoCAdmin(admin.ModelAdmin):
    list_display = ["name", "manufacturer", "cpu_architecture", "fabrication_process_nm", "release_date",
                     "performance_score", "efficiency_score", _is_synced, "last_synced_at"]
    list_filter = ["manufacturer"]
    search_fields = ["name", "manufacturer"]
    readonly_fields = ["external_id", "last_synced_at"]


@admin.register(HardwareAIProfile)
class HardwareAIProfileAdmin(admin.ModelAdmin):
    """Optional human-review surface for the AI Knowledge layer  status
    defaults to "published" (review is optional per spec), so this is only
    needed when a superuser wants to hide/edit a specific profile."""

    list_display = ["type_key", "object_id", "status", "expected_lifespan_years", "generated_at", "updated_at"]
    list_filter = ["status", "type_key"]
    readonly_fields = ["source_spec_hash", "generated_at", "updated_at"]
    actions = ["mark_reviewed", "mark_published", "mark_draft"]

    def mark_reviewed(self, request, queryset):
        queryset.update(status="reviewed")
    mark_reviewed.short_description = "Mark selected profiles as reviewed"

    def mark_published(self, request, queryset):
        queryset.update(status="published")
    mark_published.short_description = "Publish selected profiles"

    def mark_draft(self, request, queryset):
        queryset.update(status="draft")
    mark_draft.short_description = "Revert selected profiles to draft (hides them)"


@admin.register(HardwareDeviceImage)
class HardwareDeviceImageAdmin(admin.ModelAdmin):
    list_display = ["type_key", "object_id", "image_type", "source_name", "is_admin_override", "last_checked_at"]
    list_filter = ["type_key", "image_type", "is_admin_override"]
    readonly_fields = ["content_hash", "last_checked_at"]


@admin.register(HardwareFieldSource)
class HardwareFieldSourceAdmin(admin.ModelAdmin):
    """Read-only provenance ledger  who supplied each field, and when."""

    list_display = ["type_key", "object_id", "field_name", "provider_key", "fetched_at"]
    list_filter = ["type_key", "provider_key"]
    search_fields = ["field_name"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(HardwareSpecChange)
class HardwareSpecChangeAdmin(admin.ModelAdmin):
    """Read-only change history  what actually changed on a sync pass."""

    list_display = ["type_key", "object_id", "field", "old_value", "new_value", "changed_at"]
    list_filter = ["type_key", "field"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
