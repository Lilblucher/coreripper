from django.db import migrations


def create_periodic_task(apps, schema_editor):
    """Registers accounts.tasks.send_newsletter to run every Friday at 09:00
    UTC  deliberately a different day/time than 'Send weekly digest emails'
    (Monday 08:00) so a member who opts into both never gets two emails at
    once. Same django-celery-beat pattern as every other scheduled task in
    this project. Only takes effect once celery beat is actually running."""
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="9", day_of_week="5", day_of_month="*", month_of_year="*",
    )
    PeriodicTask.objects.get_or_create(
        name="Send newsletter emails",
        defaults={
            "crontab": schedule,
            "task": "accounts.tasks.send_newsletter",
        },
    )


def remove_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name="Send newsletter emails").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_refactor_authtoken_multi_session"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(create_periodic_task, remove_periodic_task),
    ]
