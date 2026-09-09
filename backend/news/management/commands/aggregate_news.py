from django.core.management.base import BaseCommand

from news.tasks import aggregate_news


class Command(BaseCommand):
    help = "Fetch trending tech items, draft AI news items, queue for review. Runs synchronously (for manual/cron use)  the scheduled version runs via Celery Beat, see news/migrations/0002."

    def handle(self, *args, **kwargs):
        result = aggregate_news()  # call the task function directly, not .delay()  synchronous for a management command
        self.stdout.write(result)
