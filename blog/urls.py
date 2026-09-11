from django.contrib.sitemaps.views import sitemap
from django.urls import path

from . import views
from .feeds import LatestPostsFeed
from .sitemaps import PostSitemap

sitemaps = {"posts": PostSitemap}

urlpatterns = [
    path("api/blog/categories/", views.categories_view, name="blog-categories"),
    path("api/blog/posts/", views.posts_view, name="blog-posts"),
    path("api/blog/posts/<slug:slug>/", views.post_detail_view, name="blog-post-detail"),
    path("api/blog/admin/categories/", views.admin_categories_view, name="blog-admin-categories"),
    path("api/blog/admin/posts/", views.admin_posts_view, name="blog-admin-posts"),
    path("api/blog/admin/posts/<int:post_id>/", views.admin_post_detail_view, name="blog-admin-post-detail"),
    path("api/blog/admin/upload-image/", views.admin_upload_image_view, name="blog-admin-upload-image"),
    path("blog/sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="blog-sitemap"),
    path("blog/rss.xml", LatestPostsFeed(), name="blog-rss"),
]
