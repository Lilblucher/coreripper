from django.contrib import admin

from .models import CreditPackPrice, FxRate, PlanPrice


@admin.register(PlanPrice)
class PlanPriceAdmin(admin.ModelAdmin):
    """Django-admin fallback  day-to-day price management lives in the Engine
    Room's Pricing tab (frontend/admin.html → /api/payments/admin/prices/)."""

    list_display = ("label", "plan", "display_amount_usd", "period_days", "is_active", "sort_order")
    list_filter = ("plan", "is_active")
    search_fields = ("label",)


@admin.register(CreditPackPrice)
class CreditPackPriceAdmin(admin.ModelAdmin):
    list_display = ("label", "credits", "display_amount_usd", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("label",)


@admin.register(FxRate)
class FxRateAdmin(admin.ModelAdmin):
    list_display = ("pair", "rate", "source", "fetched_at")
    readonly_fields = ("pair", "rate", "source", "fetched_at")
