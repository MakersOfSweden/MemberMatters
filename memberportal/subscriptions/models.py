"""A member's subscriptions, one row each, kept apart from the Profile.

Until this app the only record of a subscription was a handful of Profile
columns, overwritten each time the member signed up again. A Subscription row
is never reused: signing up again starts a new one, and the old one is kept,
cancelled, as history.

The Profile columns `stripe_subscription_id`, `subscription_status` and
`membership_plan` stay, as a mirror of the member's current subscription that
every existing reader keeps using. Only records.py writes either side.
"""

from django.db import models
from django.utils import timezone

from profile.models import Profile


class Subscription(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        # Still running, set to end at the close of the paid period.
        CANCELLING = "cancelling", "Cancelling"
        CANCELLED = "cancelled", "Cancelled"

    class Provider(models.TextChoices):
        STRIPE = "stripe", "Stripe"

    id = models.AutoField(primary_key=True)
    payer = models.ForeignKey(
        "profile.Profile", on_delete=models.CASCADE, related_name="subscriptions"
    )
    state = models.CharField(max_length=10, choices=State.choices)
    # The value Profile.subscription_status has while this is the member's
    # current subscription, kept verbatim. "pending" (an invoice signup not yet
    # paid) can't be told from "active" without payments, so this stays until
    # the status is derived from them.
    legacy_status = models.CharField(max_length=10, choices=Profile.SUBSCRIPTION_STATES)
    plan = models.ForeignKey(
        "api_admin_tools.PaymentPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subscriptions",
    )
    provider = models.CharField(
        max_length=20, choices=Provider.choices, default=Provider.STRIPE
    )
    billing_method = models.CharField(
        max_length=10, choices=Profile.BILLING_METHODS, default="card"
    )
    # The provider's id for this subscription: for Stripe, the subscription
    # id. Null and "" are kept apart because Profile.stripe_subscription_id,
    # which this is mirrored into, holds both.
    external_ref = models.CharField(
        max_length=100, null=True, blank=True, db_index=True
    )
    # Unknown for subscriptions adopted from the Profile columns.
    started_at = models.DateTimeField(null=True, blank=True)
    cancel_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(default=timezone.now, editable=False)
    modified = models.DateTimeField(auto_now=True)
    # Bumped on every write, so a change can be told from a re-read.
    version = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created", "-id"]

    def __str__(self):
        return f"Subscription {self.pk} of {self.payer} ({self.state})"

    @property
    def is_live(self):
        return self.state != self.State.CANCELLED
