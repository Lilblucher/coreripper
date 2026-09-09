from django.contrib.sitemaps.views import sitemap
from django.urls import path

from . import admin_views, views
from .sitemaps import NewsSitemap

sitemaps = {"news": NewsSitemap}

urlpatterns = [
    path("api/news/admin/", admin_views.admin_news_view, name="news-admin-list"),
    path("api/news/admin/<int:pk>/", admin_views.admin_news_detail_view, name="news-admin-detail"),
    path("api/news/admin/<int:pk>/updates/", admin_views.admin_news_add_update_view, name="news-admin-add-update"),
    path("api/news/admin/<int:pk>/image/", admin_views.admin_news_image_view, name="news-admin-image"),
    path("api/news/", views.news_feed_view, name="news-feed"),
    path("api/news/archive/", views.news_archive_view, name="news-archive"),
    path("api/news/<int:pk>/", views.news_detail_view, name="news-detail"),
    path("api/news/<int:pk>/related/", views.news_related_view, name="news-related"),
    path("news/sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="news-sitemap"),
]
