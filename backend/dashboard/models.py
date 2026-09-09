"""Premium dashboard customization models.

Only Premium users ever create rows here (enforced at the view layer via
core.decorators.premium_required), but nothing here hard-depends on the
subscription  a downgraded user's saved data is simply no longer reachable
through the Premium-gated endpoints, not deleted. `tool_key` matches the
/api/toolbox/?tool=… dispatch key (and core.Tool.tool_key), reused as-is.
"""

from django.conf import settings
from django.db import models


class DashboardSection(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dashboard_sections"
    )
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.user} · {self.name}"


class DashboardSectionTool(models.Model):
    section = models.ForeignKey(
        DashboardSection, on_delete=models.CASCADE, related_name="tools"
    )
    tool_key = models.CharField(max_length=50)  # matches /api/toolbox/?tool=…
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        # A tool appears at most once per section.
        constraints = [
            models.UniqueConstraint(fields=["section", "tool_key"], name="uniq_tool_per_section")
        ]

    def __str__(self):
        return f"{self.section.name} · {self.tool_key}"


class DashboardProject(models.Model):
    """A named group of SavedResults saved together from one completed Workbench
    batch run ("Save as Project"). Deleting a project deletes its results with
    it  a project's results have no independent existence outside their folder."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dashboard_projects"
    )
    name = models.CharField(max_length=150)
    target = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} · {self.name}"


class SavedResult(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_results"
    )
    project = models.ForeignKey(
        DashboardProject, on_delete=models.CASCADE, null=True, blank=True, related_name="results"
    )
    tool_key = models.CharField(max_length=50)
    target = models.CharField(max_length=255)     # what was looked up
    result_json = models.JSONField()              # raw tool response payload, reused as-is
    label = models.CharField(max_length=100, blank=True)  # optional user-given name
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "created_at"])]

    def __str__(self):
        return f"{self.user} · {self.tool_key} · {self.target}"
