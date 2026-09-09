from django.db import migrations


def backfill(apps, schema_editor):
    NewsDraft = apps.get_model("news", "NewsDraft")
    ArticleSource = apps.get_model("news", "ArticleSource")
    ArticleUpdate = apps.get_model("news", "ArticleUpdate")

    for draft in NewsDraft.objects.all():
        if not ArticleSource.objects.filter(article=draft).exists():
            ArticleSource.objects.create(
                article=draft, url=draft.source_url, name=draft.source_name, is_primary=True, order=0,
            )
        if draft.status == "published":
            if draft.published_at is None:
                draft.published_at = draft.reviewed_at or draft.created_at
                draft.save(update_fields=["published_at"])
            if not ArticleUpdate.objects.filter(article=draft, kind="published").exists():
                update = ArticleUpdate.objects.create(
                    article=draft, kind="published", title="Article published",
                )
                # created_at is auto_now_add  backfill it to the real publish
                # time via a queryset update, which bypasses auto_now_add.
                ArticleUpdate.objects.filter(pk=update.pk).update(created_at=draft.published_at)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0003_newsdraft_published_at_articlesource_articleupdate"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
