from django.contrib import admin

from .models import ArticleSource, ArticleUpdate, NewsDraft


class ArticleSourceInline(admin.TabularInline):
    model = ArticleSource
    extra = 0


class ArticleUpdateInline(admin.TabularInline):
    model = ArticleUpdate
    extra = 0
    readonly_fields = ["created_at"]


@admin.register(NewsDraft)
class NewsDraftAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "trending_score", "status", "created_at", "published_at"]
    list_filter = ["status", "category"]
    search_fields = ["title", "source_name"]
    readonly_fields = ["source_url", "source_name", "trending_score", "created_at", "reviewed_at", "published_at"]
    actions = ["approve_and_publish", "reject"]
    inlines = [ArticleSourceInline, ArticleUpdateInline]

    def approve_and_publish(self, request, queryset):
        # Routed through NewsDraft.publish() (not a bulk queryset.update())
        # so each draft gets its published_at stamp + timeline entry exactly
        # like the cockpit's News tab path (news/admin_views.py)  one
        # publish/reject implementation shared by both admin surfaces.
        for draft in queryset:
            draft.publish()
    approve_and_publish.short_description = "Approve and publish selected drafts"

    def reject(self, request, queryset):
        for draft in queryset:
            draft.reject()
    reject.short_description = "Reject selected drafts"
