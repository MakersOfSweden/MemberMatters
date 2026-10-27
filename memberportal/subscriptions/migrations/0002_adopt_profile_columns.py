"""Give every member with billing columns a Subscription row describing them.

A frozen copy of records.adopt_profile_columns for members with no rows yet: a
migration must not import live code, which changes. The columns are copied
verbatim, inconsistent combinations included, so the mirror reads exactly as
the columns did. Reversing deletes the rows and leaves the columns alone.
"""

from django.db import migrations
from django.db.models import Q

STATE_FOR_STATUS = {
    "active": "active",
    "pending": "active",
    "cancelling": "cancelling",
    "inactive": "cancelled",
}


def adopt(apps, schema_editor):
    Profile = apps.get_model("profile", "Profile")
    Subscription = apps.get_model("subscriptions", "Subscription")

    profiles = Profile.objects.filter(current_subscription__isnull=True).filter(
        (Q(stripe_subscription_id__isnull=False) & ~Q(stripe_subscription_id=""))
        | ~Q(subscription_status="inactive")
        | Q(membership_plan__isnull=False)
    )
    # Listed first: SQLite gives no isolation between a cursor and writes to
    # the table it reads.
    for profile in list(profiles.order_by("pk")):
        subscription = Subscription.objects.create(
            payer_id=profile.pk,
            state=STATE_FOR_STATUS[profile.subscription_status],
            legacy_status=profile.subscription_status,
            plan_id=profile.membership_plan_id,
            provider="stripe",
            billing_method=profile.billing_method,
            external_ref=profile.stripe_subscription_id,
            version=1,
        )
        Profile.objects.filter(pk=profile.pk).update(current_subscription=subscription)


def remove(apps, schema_editor):
    Profile = apps.get_model("profile", "Profile")
    Subscription = apps.get_model("subscriptions", "Subscription")

    Profile.objects.update(current_subscription=None)
    Subscription.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0001_initial"),
        ("profile", "0027_profile_current_subscription"),
    ]

    operations = [migrations.RunPython(adopt, remove)]
