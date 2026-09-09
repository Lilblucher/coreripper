from django.db import migrations


def create_periodic_task(apps, schema_editor):
    """Registers news.tasks.auto_edit_news  the Intelligent auto-editor pass
    to run daily at 03:00 UTC (after the 02:00-02:40 credits lifecycle jobs,
    before the 07:00 news aggregation), same CrontabSchedule/PeriodicTask
    mechanism as every other scheduled task here. Only runs once beat is up."""
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="3", day_of_month="*", month_of_year="*", day_of_week="*",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.get_or_create(
        name="Auto-edit published news articles",
        defaults={"crontab": schedule, "task": "news.tasks.auto_edit_news"},
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Auto-edit published news articles").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0005_newsdraft_intel_image_confidence_and_more"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
