from django.urls import path

from . import views

urlpatterns = [
    path("api/dashboard/sections/", views.sections_view, name="dashboard-sections"),
    path("api/dashboard/sections/<int:section_id>/", views.section_detail_view, name="dashboard-section-detail"),
    path("api/dashboard/sections/<int:section_id>/tools/", views.section_tools_view, name="dashboard-section-tools"),
    path("api/dashboard/sections/<int:section_id>/tools/<str:tool_key>/", views.section_tool_detail_view, name="dashboard-section-tool-detail"),
    path("api/dashboard/results/", views.results_view, name="dashboard-results"),
    path("api/dashboard/results/export/", views.results_export_view, name="dashboard-results-export"),
    path("api/dashboard/results/<int:result_id>/", views.result_detail_view, name="dashboard-result-detail"),
    path("api/dashboard/results/<int:result_id>/export/", views.result_export_view, name="dashboard-result-export"),
    path("api/dashboard/projects/", views.projects_view, name="dashboard-projects"),
    path("api/dashboard/projects/<int:project_id>/", views.project_detail_view, name="dashboard-project-detail"),
    path("api/dashboard/projects/<int:project_id>/export/", views.project_export_view, name="dashboard-project-export"),
    path("api/dashboard/projects/<int:project_id>/report/", views.project_report_view, name="dashboard-project-report"),
    path("api/dashboard/projects/<int:project_id>/report/pdf/", views.project_report_pdf_view, name="dashboard-project-report-pdf"),
    path("api/dashboard/fix/", views.fix_view, name="dashboard-fix"),
    path("api/dashboard/assistant/", views.assistant_view, name="dashboard-assistant"),
]
