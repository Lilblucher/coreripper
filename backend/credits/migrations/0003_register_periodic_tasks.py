from django.db import migrations

# (task path, PeriodicTask name, minute, hour). Ordered 02:00 → 02:40 so trial
# expiry, renewal requests, monthly refresh, unrenewed expiry, and pack expiry
# run in a sensible sequence. Only takes effect once celery beat is running.
TASKS = [
    ("credits.tasks.expire_trials", "Expire ended trials", "0", "2"),
    ("credits.tasks.request_renewals", "Request subscription renewals", "10", "2"),
    ("credits.tasks.refresh_subscription_credits", "Refresh subscription credits", "20", "2"),
    ("credits.tasks.expire_unrenewed", "Expire unrenewed subscriptions", "30", "2"),
    ("credits.tasks.expire_pack_credits", "Expire pack credits", "40", "2"),
]


def create_periodic_tasks(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    for task, name, minute, hour in TASKS:
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=minute, hour=hour, day_of_month="*", month_of_year="*", day_of_week="*",
            defaults={"timezone": "UTC"},
        )
        PeriodicTask.objects.get_or_create(
            name=name, defaults={"crontab": schedule, "task": task}
        )


def remove_periodic_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name__in=[name for _, name, _, _ in TASKS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("credits", "0002_backfill_wallets"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(create_periodic_tasks, remove_periodic_tasks),
    ]
