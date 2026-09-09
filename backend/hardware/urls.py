from django.contrib.sitemaps.views import sitemap
from django.urls import path

from . import admin_views, views
from .sitemaps import HardwareSitemap

sitemaps = {"hardware": HardwareSitemap}

urlpatterns = [
    # Admin / moderation (superuser_required  mirrors news' admin API shape)
    path("api/hardware/admin/articles/", admin_views.admin_hardware_articles_view, name="hardware-admin-list"),
    path(
        "api/hardware/admin/articles/<int:pk>/",
        admin_views.admin_hardware_article_detail_view,
        name="hardware-admin-detail",
    ),
    path(
        "api/hardware/admin/articles/<int:pk>/updates/",
        admin_views.admin_hardware_article_add_update_view,
        name="hardware-admin-add-update",
    ),
    path(
        "api/hardware/admin/articles/<int:pk>/image/",
        admin_views.admin_hardware_article_image_view,
        name="hardware-admin-image",
    ),
    # Public articles
    path("api/hardware/articles/", views.hardware_articles_view, name="hardware-articles"),
    path("api/hardware/articles/<int:pk>/", views.hardware_article_detail_view, name="hardware-article-detail"),
    path("hardware/sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="hardware-sitemap"),
]
