from django.db import models
from django.utils import timezone


class ScamRule(models.Model):
    """A single scam-detection regex rule, stored in the DB so it can be
    added/edited/disabled without a code deploy."""

    SOURCE_CHOICES = [
        ('seed', 'Seed (hardcoded original)'),
        ('admin', 'Admin (manually added)'),
        ('ai', 'AI-generated'),
    ]

    code = models.CharField(max_length=80, unique=True)
    weight = models.PositiveSmallIntegerField(default=10)
    pattern = models.TextField(help_text='Python regex pattern (case-insensitive)')
    label = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True, db_index=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='admin')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-weight', 'code']

    def __str__(self):
        return f'{self.code} (w={self.weight}, {"on" if self.is_active else "off"})'


class ScamShortener(models.Model):
    """A URL-shortener domain used in link analysis."""

    SOURCE_CHOICES = [
        ('seed', 'Seed'),
        ('admin', 'Admin'),
        ('auto', 'Auto-fetched'),
    ]

    domain = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True, db_index=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='admin')
    added_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['domain']

    def __str__(self):
        return self.domain


class ScamUpdateLog(models.Model):
    """Tracks each auto-update run so admins can see what changed."""

    run_at = models.DateTimeField(default=timezone.now)
    rules_added = models.PositiveIntegerField(default=0)
    rules_updated = models.PositiveIntegerField(default=0)
    shorteners_added = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=20, default='ai')
    details = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-run_at']

    def __str__(self):
        return f'{self.run_at:%Y-%m-%d %H:%M} +{self.rules_added}r +{self.shorteners_added}s'


class BreachAlert(models.Model):
    """Recent major data breaches shown as context on the Password Breach
    Checker page - fetched periodically from the HIBP API."""

    name = models.CharField(max_length=200, unique=True)
    title = models.CharField(max_length=200)
    domain = models.CharField(max_length=200, blank=True, default='')
    breach_date = models.DateField(null=True, blank=True)
    added_date = models.DateField(null=True, blank=True)
    pwn_count = models.BigIntegerField(default=0)
    description = models.TextField(blank=True, default='')
    data_classes = models.JSONField(default=list, blank=True)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-breach_date']

    def __str__(self):
        return f'{self.title} ({self.breach_date})'
