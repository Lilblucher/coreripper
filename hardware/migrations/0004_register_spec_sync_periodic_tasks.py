from django.db import migrations


def create_periodic_tasks(apps, schema_editor):
    """Registers sync_hardware_specs (manage.py command, run via
    hardware.providers.manager.sync_type) on four cadences, mirroring
    news/migrations/0002 and hardware/migrations/0002's own
    CrontabSchedule-based approach rather than an actual crontab entry.
    Cadence mirrors how fast each category's real-world data actually
    churns: phones fastest, CPUs slowest. Only takes effect once celery
    beat is actually running (see CLAUDE.md  worker/beat are hand-started,
    not services on this box)."""
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    def register(name, type_key, **crontab_kwargs):
        schedule, _ = CrontabSchedule.objects.get_or_create(
            defaults={"timezone": "UTC"}, **crontab_kwargs,
        )
        PeriodicTask.objects.get_or_create(
            name=name,
            defaults={
                "crontab": schedule,
                "task": "hardware.tasks.sync_hardware_spec_type",
                "kwargs": f'{{"type_key": "{type_key}"}}',
            },
        )

    register(
        "Sync mobile SoC specs (daily)", "mobile_soc",
        minute="0", hour="4", day_of_month="*", month_of_year="*", day_of_week="*",
    )
    register(
        "Sync laptop specs (weekly)", "laptop",
        minute="0", hour="4", day_of_month="*", month_of_year="*", day_of_week="1",
    )
    register(
        "Sync GPU specs (weekly)", "gpu",
        minute="30", hour="4", day_of_month="*", month_of_year="*", day_of_week="1",
    )
    register(
        "Sync CPU specs (monthly)", "cpu",
        minute="0", hour="5", day_of_month="1", month_of_year="*", day_of_week="*",
    )


def remove_periodic_tasks(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name__in=[
            "Sync mobile SoC specs (daily)",
            "Sync laptop specs (weekly)",
            "Sync GPU specs (weekly)",
            "Sync CPU specs (monthly)",
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("hardware", "0003_hardwarespecchange_cpu_efficiency_score_and_more"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(create_periodic_tasks, remove_periodic_tasks),
    ]
