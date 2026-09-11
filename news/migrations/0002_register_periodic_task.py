from django.db import migrations


def create_periodic_task(apps, schema_editor):
    """Registers news.tasks.aggregate_news to run at 07:00 and 19:00 UTC 
    per the spec's cron line (avoids notifications landing mid-lecture),
    reimplemented as a django_celery_beat CrontabSchedule instead of an
    actual crontab entry, matching how every other scheduled task in this
    project works (monitors/migrations/0002, accounts/migrations/0008). Only
    takes effect once celery beat is actually running."""
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="7,19", day_of_month="*", month_of_year="*", day_of_week="*",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.get_or_create(
        name="Aggregate trending news drafts",
        defaults={
            "crontab": schedule,
            "task": "news.tasks.aggregate_news",
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Aggregate trending news drafts").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0001_initial"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, remove_periodic_task),
    ]
