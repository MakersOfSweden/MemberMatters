from django.conf import settings
from django.db import models
from django.utils import timezone


class Severity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    CRITICAL = "critical", "Critical"


SEVERITY_RANK = {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}


class Source(models.TextChoices):
    """Which local record of a subscription a finding compares with Stripe.

    Checks that don't read a member's subscription (plans, the webhook
    endpoint) use ACCOUNT and run once whichever sources are enabled.
    """

    ACCOUNT = "account", "Stripe account"
    LEGACY = "legacy", "Current system"
    SUBSCRIPTIONS = "subscriptions", "Subscription table"


class IntegrityRun(models.Model):
    """One run of the integrity checks, scheduled or on demand."""

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        # Every check ran over its whole scope.
        COMPLETE = "complete", "Complete"
        # Some checks were skipped or cut short. Their open issues are left
        # as they were, neither updated nor resolved.
        INCOMPLETE = "incomplete", "Incomplete"
        # Nothing could be checked, e.g. Stripe refused the secret key.
        FAILED = "failed", "Failed"

    class Trigger(models.TextChoices):
        SCHEDULE = "schedule", "Schedule"
        MANUAL = "manual", "Run now"
        COMMAND = "command", "Management command"
        MEMBER = "member", "Member re-check"

    id = models.AutoField(primary_key=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RUNNING
    )
    trigger = models.CharField(max_length=20, choices=Trigger.choices)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Set on a member re-check: the run only looked at this member.
    profile = models.ForeignKey(
        "profile.Profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    stripe_requests = models.PositiveIntegerField(default=0)
    members_checked = models.PositiveIntegerField(default=0)
    new_issues = models.PositiveIntegerField(default=0)
    resolved_issues = models.PositiveIntegerField(default=0)
    open_issues = models.PositiveIntegerField(default=0)
    # [{"check": ..., "reason": ...}] for every check that didn't run fully.
    skipped_checks = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Integrity run {self.pk} ({self.trigger}, {self.status})"

    @property
    def is_full(self):
        return self.profile_id is None and self.trigger != self.Trigger.MEMBER


class IntegrityIssue(models.Model):
    """Something a check found wrong, and still finds wrong.

    One row per distinct issue, keyed by check, source and subject: every run
    that still observes it bumps `occurrences` and `last_seen`, and a complete
    run that no longer observes it sets `resolved_at`. If it comes back later,
    the same row reopens as a new occurrence.

    The checks only report. Nothing here, or in the runs that write it,
    changes a member or calls a Stripe write endpoint.
    """

    id = models.AutoField(primary_key=True)
    key = models.CharField(max_length=255, unique=True)
    # Not `check`: that would shadow Model.check(), which the system check
    # framework calls on every model class.
    check_name = models.CharField(max_length=64, db_index=True)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    source = models.CharField(max_length=20, choices=Source.choices)
    profile = models.ForeignKey(
        "profile.Profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="integrity_issues",
    )
    subscription = models.ForeignKey(
        "subscriptions.Subscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="integrity_issues",
    )
    # The Stripe object the issue is about: a subscription, price or endpoint.
    stripe_ref = models.CharField(max_length=255, blank=True)
    # A one-line summary written for an admin, e.g. "Cancelled in Stripe,
    # still active here".
    message = models.CharField(max_length=255)
    # "mm" and "stripe" (what each side says), "cause" and "action" are shown
    # to admins; anything else is context for debugging.
    details = models.JSONField(default=dict, blank=True)
    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    occurrences = models.PositiveIntegerField(default=1)
    resolved_at = models.DateTimeField(null=True, blank=True)
    # The highest severity an admin has been emailed about for this
    # occurrence. Empty until the first alert; a run only emails about an
    # issue whose severity has risen above it.
    notified_severity = models.CharField(
        max_length=10, choices=Severity.choices, blank=True
    )
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-last_seen"]
        indexes = [models.Index(fields=["resolved_at", "severity"])]

    def __str__(self):
        return f"{self.get_severity_display()}: {self.message} ({self.key})"

    @property
    def is_open(self):
        return self.resolved_at is None

    @property
    def is_acknowledged(self):
        return self.acknowledged_at is not None
