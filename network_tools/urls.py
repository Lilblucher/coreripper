from django.urls import path
from . import views
from . import admin_views

urlpatterns = [
    path("api/toolbox/security-grade/badge.svg", views.security_grade_badge_svg, name="security-grade-badge"),
    path("api/toolbox/security-grade/card.png", views.security_grade_card_png, name="security-grade-card"),
    path("api/toolbox/", views.network_toolbox_view, name="network-toolbox"),

    # Public: breach alerts for the password breach checker page
    path("api/toolbox/breach-alerts/", admin_views.breach_alerts_view, name="breach-alerts"),

    # Admin: scam detection rules management
    path("api/toolbox/admin/scam-rules/", admin_views.admin_scam_rules_view, name="admin-scam-rules"),
    path("api/toolbox/admin/scam-rules/<int:rule_id>/", admin_views.admin_scam_rule_detail_view, name="admin-scam-rule-detail"),
    path("api/toolbox/admin/scam-shorteners/", admin_views.admin_scam_shorteners_view, name="admin-scam-shorteners"),
    path("api/toolbox/admin/scam-shorteners/<int:shortener_id>/", admin_views.admin_scam_shortener_detail_view, name="admin-scam-shortener-detail"),
    path("api/toolbox/admin/scam-update-logs/", admin_views.admin_scam_update_logs_view, name="admin-scam-update-logs"),
]
