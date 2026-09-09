from django.db import migrations


def reschedule_weekly(apps, schema_editor):
    """Moves blog.tasks.auto_edit_blog from daily 03:40 UTC to weekly, Monday
    03:40 UTC  one day after news.tasks.news_weekly_wrapup clears the news
    feed (Sunday 03:50 UTC, news/migrations/0007). Points the existing
    PeriodicTask row at a new weekly CrontabSchedule rather than deleting and
    recreating it, so its run history/enabled flag survive untouched."""
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="40", hour="3", day_of_month="*", month_of_year="*", day_of_week="1",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.filter(name="Auto-edit published blog posts").update(crontab=schedule)


def revert_to_daily(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="40", hour="3", day_of_month="*", month_of_year="*", day_of_week="*",
        defaults={"timezone": "UTC"},
    )
    PeriodicTask.objects.filter(name="Auto-edit published blog posts").update(crontab=schedule)


class Migration(migrations.Migration):

    dependencies = [
        ("blog", "0006_register_auto_edit_task"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(reschedule_weekly, revert_to_daily)]
