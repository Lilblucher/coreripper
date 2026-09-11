from django.db import migrations


def create_periodic_task(apps, schema_editor):
    """Registers hardware.tasks.aggregate_hardware_content to run at 07:00
    and 19:00 UTC  same cadence as news.tasks.aggregate_news
    (news/migrations/0002_register_periodic_task.py), for consistency
    across this project's scheduled content-ingestion tasks. Only takes
    effect once celery beat is actually running, and only does anything
    once the provider registry is non-empty (see
    hardware/providers/registry.py)  which it now is."""
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="7,19", day_of_month="*", month_of_year="*", day_of_week="*",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.get_or_create(
        name="Aggregate hardware/gaming content",
        defaults={
            "crontab": schedule,
            "task": "hardware.tasks.aggregate_hardware_content",
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Aggregate hardware/gaming content").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("hardware", "0001_initial"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, remove_periodic_task),
    ]
