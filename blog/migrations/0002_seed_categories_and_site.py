from django.db import migrations

CATEGORIES = [
    ("Programming", "programming", "Backend, frontend, and general software development"),
    ("Linux", "linux", "Command line, containers, and systems administration"),
    ("Networking", "networking", "DNS, protocols, and network infrastructure"),
    ("Artificial Intelligence", "ai", "AI tooling, LLMs, and applied machine learning"),
    ("Cybersecurity", "cybersecurity", "Web security, vulnerabilities, and defensive practices"),
]


def seed_categories(apps, schema_editor):
    Category = apps.get_model("blog", "Category")
    for order, (name, slug, description) in enumerate(CATEGORIES):
        Category.objects.update_or_create(
            slug=slug, defaults={"name": name, "description": description, "order": order}
        )


def unseed_categories(apps, schema_editor):
    Category = apps.get_model("blog", "Category")
    Category.objects.filter(slug__in=[slug for _, slug, _ in CATEGORIES]).delete()


def set_site_domain(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.update_or_create(
        id=1, defaults={"domain": "127.0.0.1:8000", "name": "CoreLom"}
    )


def revert_site_domain(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(id=1).update(domain="example.com", name="example.com")


class Migration(migrations.Migration):

    dependencies = [
        ("blog", "0001_initial"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed_categories),
        migrations.RunPython(set_site_domain, revert_site_domain),
    ]
