from django.db import migrations


def reschedule_monthly(apps, schema_editor):
    """Moves hardware.tasks.auto_edit_hardware from daily 03:20 UTC to
    monthly, 1st-of-month 03:20 UTC. Note: this only affects the article-level
    auto-editor pass  the separate CPU/GPU/Laptop/SoC spec-sync schedule
    (hardware/migrations/0004, sync_hardware_spec_type per type) is untouched
    by design. Points the existing PeriodicTask row at a new monthly
    CrontabSchedule rather than deleting and recreating it, so its run
    history/enabled flag survive untouched."""
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="20", hour="3", day_of_month="1", month_of_year="*", day_of_week="*",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.filter(name="Auto-edit published hardware articles").update(crontab=schedule)


def revert_to_daily(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="20", hour="3", day_of_month="*", month_of_year="*", day_of_week="*",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.filter(name="Auto-edit published hardware articles").update(crontab=schedule)


class Migration(migrations.Migration):

    dependencies = [
        ("hardware", "0008_register_auto_edit_task"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(reschedule_monthly, revert_to_daily)]
