from django.db import migrations


def create_periodic_task(apps, schema_editor):
    """Registers news.tasks.news_weekly_wrapup  weekly on Sunday 03:50 UTC,
    the day before blog's auto-editor moves to Monday 03:40 UTC (see
    blog/migrations/0007) and well ahead of hardware's monthly run (see
    hardware/migrations/0009). Summarizes + clears the published news feed
    every 7 days; see news/tasks.py for the full mechanics."""
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="50", hour="3", day_of_month="*", month_of_year="*", day_of_week="0",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.get_or_create(
        name="Weekly news wrap-up + clear",
        defaults={"crontab": schedule, "task": "news.tasks.news_weekly_wrapup"},
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Weekly news wrap-up + clear").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0006_register_auto_edit_task"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
