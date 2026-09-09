from django.db import migrations


def create_periodic_task(apps, schema_editor):
    """Registers monitors.tasks.dispatch_due_monitors to run every 5 minutes,
    via django-celery-beat's DB-backed schedule  per
    PHASE2_MONITORING_ALERTS.md §3a ("do this via a data migration ... not
    hardcoded"). Only takes effect once celery beat is actually running
    (see MONITORING_SETUP_COMMANDS.md)."""
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = IntervalSchedule.objects.get_or_create(every=5, period="minutes")
    PeriodicTask.objects.get_or_create(
        name="Dispatch due monitor checks",
        defaults={
            "interval": schedule,
            "task": "monitors.tasks.dispatch_due_monitors",
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Dispatch due monitor checks").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("monitors", "0001_initial"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, remove_periodic_task),
    ]
