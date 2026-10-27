"""The single writer for subscriptions, and for the Profile columns mirroring them.

Every change to a member's subscription goes through a function here. Each
updates the member's Subscription rows and then calls sync_profile_mirror(),
which writes the three Profile columns every reader still uses:
membership_plan, stripe_subscription_id and subscription_status. Nothing else
assigns those columns.

Callers hold the member's Profile row lock (select_for_update) and pass that
locked instance. Nothing here takes a lock of its own.

While readers use the columns, the columns win any disagreement. Each change
first adopts them (adopt_profile_columns), so a member whose rows are missing
or out of date is brought into line before the change is made: a member from
before this table existed, one edited in the Django admin, or one written by
older code after a rollback. That way the columns always end up exactly as the
code before this table left them.
"""

import logging

from django.db.models import Q
from django.utils import timezone

from .models import Subscription

logger = logging.getLogger("billing")

# How each Profile.subscription_status value reads as a Subscription state.
STATE_FOR_STATUS = {
    "active": Subscription.State.ACTIVE,
    # An invoice signup waiting for its first payment, which Stripe already
    # counts as active.
    "pending": Subscription.State.ACTIVE,
    "cancelling": Subscription.State.CANCELLING,
    "inactive": Subscription.State.CANCELLED,
}

MIRRORED_FIELDS = ("membership_plan", "stripe_subscription_id", "subscription_status")


class NoCurrentSubscription(Exception):
    """A change was asked for on a member with no current subscription."""


def mirror_values(subscription):
    """The mirrored columns, by attribute name, while `subscription` is current."""
    if subscription is None:
        return {
            "membership_plan_id": None,
            "stripe_subscription_id": None,
            "subscription_status": "inactive",
        }
    return {
        "membership_plan_id": subscription.plan_id,
        "stripe_subscription_id": subscription.external_ref,
        "subscription_status": subscription.legacy_status,
    }


def has_billing_columns(profile):
    """Whether the mirrored columns describe a subscription at all."""
    return (
        bool(profile.stripe_subscription_id)
        or profile.subscription_status != "inactive"
        or profile.membership_plan_id is not None
    )


def has_billing_columns_q():
    """Members with billing columns or a current subscription: everyone whose
    rows and columns could disagree."""
    return (
        (Q(stripe_subscription_id__isnull=False) & ~Q(stripe_subscription_id=""))
        | ~Q(subscription_status="inactive")
        | Q(membership_plan__isnull=False)
        | Q(current_subscription__isnull=False)
    )


def mirror_matches(profile):
    """Whether the columns say what the member's current subscription says.

    Without a current subscription the columns need only be empty: a member
    who never subscribed has "" where one whose subscription ended has None.
    """
    current = profile.current_subscription
    if current is None:
        return not has_billing_columns(profile)
    return all(
        getattr(profile, attribute) == value
        for attribute, value in mirror_values(current).items()
    )


def _save(subscription):
    subscription.version += 1
    subscription.save()


def _set_status(subscription, status):
    subscription.legacy_status = status
    subscription.state = STATE_FOR_STATUS[status]


def _close(subscription, now):
    _set_status(subscription, "inactive")
    if subscription.cancelled_at is None:
        subscription.cancelled_at = now
    _save(subscription)


def adopt_profile_columns(profile, now=None):
    """Bring the member's subscription rows in line with the Profile columns.

    Returns whether anything changed. Writes rows and the current pointer,
    never the columns.
    """
    if mirror_matches(profile):
        return False

    now = now or timezone.now()
    current = profile.current_subscription
    if (
        current is not None
        and has_billing_columns(profile)
        and current.external_ref == profile.stripe_subscription_id
    ):
        # The same subscription, with another plan or status.
        current.plan_id = profile.membership_plan_id
        _set_status(current, profile.subscription_status)
        _save(current)
        logger.warning(
            "Updated subscription %s of profile %s from its billing columns.",
            current.pk,
            profile.pk,
        )
        return True

    if current is not None:
        _close(current, now)
    if has_billing_columns(profile):
        adopted = Subscription(
            payer=profile,
            plan_id=profile.membership_plan_id,
            external_ref=profile.stripe_subscription_id,
            billing_method=profile.billing_method,
        )
        _set_status(adopted, profile.subscription_status)
        _save(adopted)
    else:
        adopted = None
    profile.current_subscription = adopted
    profile.save(update_fields=["current_subscription"])
    logger.warning(
        "Adopted the billing columns of profile %s: subscription %s replaces %s.",
        profile.pk,
        adopted.pk if adopted else None,
        current.pk if current else None,
    )
    return True


def sync_profile_mirror(profile):
    """Write the mirrored columns from the member's current subscription."""
    for attribute, value in mirror_values(profile.current_subscription).items():
        setattr(profile, attribute, value)
    profile.save(update_fields=["current_subscription", *MIRRORED_FIELDS])


def _current(profile, now):
    adopt_profile_columns(profile, now)
    if profile.current_subscription is None:
        raise NoCurrentSubscription(
            f"Profile {profile.pk} has no current subscription."
        )
    return profile.current_subscription


def start(profile, *, external_ref, plan, billing_method, status, now=None):
    """Record a subscription the member has just taken out, as their current one.

    `status` is the Profile.subscription_status it starts with. A subscription
    still current is closed, as the new one replaces it.
    """
    now = now or timezone.now()
    adopt_profile_columns(profile, now)
    if profile.current_subscription is not None:
        _close(profile.current_subscription, now)

    subscription = Subscription(
        payer=profile,
        plan=plan,
        external_ref=external_ref,
        billing_method=billing_method,
        started_at=now,
    )
    _set_status(subscription, status)
    _save(subscription)
    profile.current_subscription = subscription
    sync_profile_mirror(profile)
    return subscription


def _change_status(profile, status, now):
    current = _current(profile, now or timezone.now())
    _set_status(current, status)
    _save(current)
    sync_profile_mirror(profile)
    return current


def mark_cancelling(profile, now=None):
    """The member's current subscription is set to end with its paid period."""
    return _change_status(profile, "cancelling", now)


def mark_active(profile, now=None):
    """The member's current subscription runs on: resumed, or paid for."""
    return _change_status(profile, "active", now)


def end(profile, now=None):
    """End the member's current subscription, and return it.

    The columns are cleared even when there was nothing current, as the code
    before this table always cleared them.
    """
    now = now or timezone.now()
    adopt_profile_columns(profile, now)
    ended = profile.current_subscription
    if ended is not None:
        _close(ended, now)
    profile.current_subscription = None
    sync_profile_mirror(profile)
    return ended
