# In your main project's urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("network_tools.urls")),  # Includes the toolbox paths
]
