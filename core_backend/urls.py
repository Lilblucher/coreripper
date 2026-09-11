"""
URL configuration for core_backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

import os
from pathlib import Path

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as static_serve

# Blog article images are uploaded by staff/admin through the editor and land
# here  a directory OUTSIDE the git repo (Documents/Core) on purpose. VS
# Code Live Server (serving the frontend at dev time) watches the whole repo
# by default; a directory inside it that receives writes mid-edit triggers a
# live-reload that wipes whatever's open in the editor. Living outside the
# repo means uploads can never trigger that, no matter how Live Server's
# watch scope is configured. Default resolves against the *running* OS
# user's home (clive locally, deploy on the VPS) instead of a hardcoded
# literal, which otherwise silently 500s every upload once this runs under
# a different account  override with BLOG_IMAGES_ROOT if a deployment needs
# the directory somewhere else entirely.
BLOG_IMAGES_DIR = Path(
    os.environ.get("BLOG_IMAGES_ROOT") or str(Path.home() / "coreripper-media" / "blog-images")
)
BLOG_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("accounts.urls")),  # Site-wide signup/login/me + admin users & transactions
    path("", include("network_tools.urls")),  # Includes the toolbox paths
    path("", include("core.urls")),  # Premium AI tool endpoints + tools registry
    path("", include("payments.urls")),  # Stub payment charge/verify endpoints
    path("", include("credits.urls")),  # Wallet balance + usage history for the credit meter
    path("", include("blog.urls")),  # Blog API, sitemap, RSS
    path("", include("dashboard.urls")),  # Premium dashboard: sections, saved results, export
    path("", include("monitors.urls")),  # Premium monitors: scheduled checks + alert history
    path("", include("news.urls")),  # Public news feed (moderation queue lives in Django admin)
    path("", include("hardware.urls")),  # Hardware & Gaming knowledge hub backend architecture
    re_path(
        r"^blog-images/(?P<path>.*)$",
        static_serve,
        {"document_root": BLOG_IMAGES_DIR},
        name="blog-images",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
