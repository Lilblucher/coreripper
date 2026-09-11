from django.contrib import admin

from .models import AIUsageRecord, CreditLedger, CreditWallet, PackCreditLot


@admin.register(CreditWallet)
class CreditWalletAdmin(admin.ModelAdmin):
    list_display = ("user", "subscription_balance", "pack_balance", "last_refresh_at", "updated_at")
    search_fields = ("user__email", "user__username")
    readonly_fields = ("subscription_balance", "pack_balance", "last_refresh_at", "updated_at")


class _ReadOnlyAdmin(admin.ModelAdmin):
    """Ledger, lots, and usage are records of fact  never editable in the admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CreditLedger)
class CreditLedgerAdmin(_ReadOnlyAdmin):
    list_display = ("user", "delta", "bucket", "reason", "operation", "balance_after", "created_at")
    list_filter = ("bucket", "reason")
    search_fields = ("user__email", "user__username", "operation")


@admin.register(PackCreditLot)
class PackCreditLotAdmin(_ReadOnlyAdmin):
    list_display = ("user", "credits_remaining", "credits_granted", "expires_at", "created_at")
    search_fields = ("user__email", "user__username", "purchase_ref")


@admin.register(AIUsageRecord)
class AIUsageRecordAdmin(_ReadOnlyAdmin):
    list_display = ("user", "operation", "model", "tokens_in", "tokens_out", "credits_charged", "created_at")
    list_filter = ("model", "operation")
    search_fields = ("user__email", "user__username", "operation")
