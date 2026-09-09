from django.db import migrations


def create_periodic_task(apps, schema_editor):
    """Registers hardware.tasks.auto_edit_hardware  the Intelligent auto-editor
    pass  at 03:20 UTC daily (staggered off news' 03:00 so the two don't
    contend for the shared Gemini key / worker at once)."""
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="20", hour="3", day_of_month="*", month_of_year="*", day_of_week="*",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.get_or_create(
        name="Auto-edit published hardware articles",
        defaults={"crontab": schedule, "task": "hardware.tasks.auto_edit_hardware"},
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Auto-edit published hardware articles").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("hardware", "0007_hardwarearticle_intel_image_confidence_and_more"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(create_periodic_task, remove_periodic_task)]
