from django.urls import path

from . import cockpit_views, image_admin_views, stats_views, subnet_views, tools_views, views

urlpatterns = [
    path("api/core/admin/category-images/", image_admin_views.admin_category_images_view, name="admin-category-images"),
    path("api/core/subnet-streak/", subnet_views.subnet_streak_view, name="subnet-streak"),
    path("api/core/subnet-streak/log/", subnet_views.subnet_streak_log_view, name="subnet-streak-log"),
    path("api/ai-tools/feedback-tutor/", views.feedback_tutor_view, name="ai-feedback-tutor"),
    path("api/ai-tools/quiz-generator/", views.quiz_generator_view, name="ai-quiz-generator"),
    path("api/ai-tools/coding-helper/", views.coding_helper_view, name="ai-coding-helper"),
    path("api/admin/tools/", tools_views.admin_tools_view, name="admin-tools"),
    path("api/admin/tools/<int:tool_id>/", tools_views.admin_tool_detail_view, name="admin-tool-detail"),
    path("api/tools/runnable/", tools_views.runnable_tools_view, name="runnable-tools"),
    path("api/stats/", stats_views.public_stats_view, name="public-stats"),
    path("api/features/", cockpit_views.public_features_view, name="public-features"),
    path("api/admin/features/", cockpit_views.admin_features_view, name="admin-features"),
    path("api/admin/features/<slug:key>/", cockpit_views.admin_feature_toggle_view, name="admin-feature-toggle"),
    path("api/admin/activity/", cockpit_views.admin_activity_view, name="admin-activity"),
    path("api/admin/systems/", cockpit_views.admin_systems_view, name="admin-systems"),
]
