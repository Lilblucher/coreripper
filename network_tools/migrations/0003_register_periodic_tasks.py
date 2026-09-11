"""Register Celery Beat tasks for auto-updating scam detection patterns
(weekly, Monday 04:00 UTC) and breach alerts (weekly, Wednesday 04:00 UTC)."""

from django.db import migrations


def create_tasks(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    weekly_mon, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="4", day_of_month="*",
        month_of_year="*", day_of_week="1",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.get_or_create(
        name="Update scam detection patterns (AI)",
        defaults={
            "crontab": weekly_mon,
            "task": "network_tools.update_scam_patterns",
        },
    )

    weekly_wed, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="4", day_of_month="*",
        month_of_year="*", day_of_week="3",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.get_or_create(
        name="Fetch recent breach alerts (HIBP)",
        defaults={
            "crontab": weekly_wed,
            "task": "network_tools.fetch_breach_alerts",
        },
    )


def remove_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name__in=[
            "Update scam detection patterns (AI)",
            "Fetch recent breach alerts (HIBP)",
        ]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("network_tools", "0002_seed_scam_rules"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]
    operations = [
        migrations.RunPython(create_tasks, remove_tasks),
    ]
