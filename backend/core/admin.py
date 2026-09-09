from django.contrib import admin

from .models import CategoryImage, Tool


@admin.register(Tool)
class ToolAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "status", "updated_at")
    list_filter = ("category", "status")
    search_fields = ("name", "path")


@admin.register(CategoryImage)
class CategoryImageAdmin(admin.ModelAdmin):
    list_display = ("app", "category", "credit_name", "license_name", "fetched_at")
    list_filter = ("app", "category")
