from django.contrib import admin

from .models import AuthToken, Payment, Subscription, UsageLog
from .subscription_utils import settle_payment


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "renewal_state", "current_period_end", "is_premium", "updated_at")
    list_filter = ("plan", "status", "renewal_state")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(boolean=True, description="Currently premium")
    def is_premium(self, obj):
        return obj.is_premium


@admin.register(UsageLog)
class UsageLogAdmin(admin.ModelAdmin):
    list_display = ("user", "tool", "tokens_in", "tokens_out", "est_cost_usd", "cache_hit", "created_at")
    list_filter = ("tool", "cache_hit")
    search_fields = ("user__username", "tool")
    date_hierarchy = "created_at"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "currency", "provider", "status", "created_at")
    list_filter = ("provider", "status", "currency")
    search_fields = ("user__username", "user__email", "provider_ref")
    actions = ["mark_paid_and_activate_premium"]

    @admin.action(description="Mark selected payments as paid & activate Premium")
    def mark_paid_and_activate_premium(self, request, queryset):
        """The StubProvider soft-launch path from the implementation spec (section 6): until a real
        payment gateway is approved, a site admin manually confirms mobile-money payments
        received off-platform and flips the payer to Premium here.

        Delegates to settle_payment(), the same idempotent settlement used by the
        gateway verify/webhook flow  so re-running this on an already-paid payment
        never double-extends, the period honors the payment's own period_days
        snapshot, and the payer gets the same receipt email."""
        activated = 0
        for payment in queryset:
            if settle_payment(payment.pk):
                activated += 1
        skipped = queryset.count() - activated
        note = f" ({skipped} already settled, skipped)" if skipped else ""
        self.message_user(request, f"Activated Premium for {activated} payment(s).{note}")


@admin.register(AuthToken)
class AuthTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "key", "created_at")
    readonly_fields = ("key",)
    search_fields = ("user__username", "user__email")
