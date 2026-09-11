from django.db import migrations


def create_periodic_task(apps, schema_editor):
    """Registers blog.tasks.auto_edit_blog  the Intelligent auto-editor pass
    at 03:40 UTC daily (staggered off news 03:00 / hardware 03:20). Blog is the
    conservative case: it only refreshes body text for posts flagged
    auto_managed; hand-written posts get image + SEO only."""
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="40", hour="3", day_of_month="*", month_of_year="*", day_of_week="*",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.get_or_create(
        name="Auto-edit published blog posts",
        defaults={"crontab": schedule, "task": "blog.tasks.auto_edit_blog"},
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Auto-edit published blog posts").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("blog", "0005_post_auto_managed_post_intel_image_confidence_and_more"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
