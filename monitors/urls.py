from django.urls import path

from . import views

urlpatterns = [
    path("api/monitors/", views.monitors_view, name="monitors"),
    path("api/monitors/alerts/mark-seen/", views.mark_alerts_seen_view, name="monitors-mark-seen"),
    path("api/monitors/whatsapp/status/", views.whatsapp_status_view, name="monitors-whatsapp-status"),
    path("api/monitors/whatsapp/test/", views.whatsapp_test_view, name="monitors-whatsapp-test"),
    path("api/monitors/<int:monitor_id>/", views.monitor_detail_view, name="monitor-detail"),
    path("api/monitors/<int:monitor_id>/alerts/", views.monitor_alerts_view, name="monitor-alerts"),
]
