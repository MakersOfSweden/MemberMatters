"""Where the checks read what MemberMatters says about each subscription.

Two sources: the billing columns on Profile, which every reader still uses, and
the Subscription table those columns mirror. While the columns are what the
portal acts on, the Stripe checks run against them alone; the table is checked
for agreeing with them, and with itself. The two swap roles when the portal
starts acting on the table.
"""

from django.db.models import Count, Q

from profile.models import Profile
from subscriptions.models import Subscription
from subscriptions.records import has_billing_columns_q

from .checks import CHECKS, SUBSCRIPTION_TABLE_CHECKS
from .data import LocalBilling
from .models import Source


def _from_columns(profile):
    return LocalBilling(
        profile_id=profile.pk,
        name=profile.get_full_name(),
        customer_id=profile.stripe_customer_id or None,
        subscription_id=profile.stripe_subscription_id or None,
        status=profile.subscription_status,
        price_id=(
            profile.membership_plan.stripe_id if profile.membership_plan else None
        ),
        billing_method=profile.billing_method,
        member_state=profile.state,
        state_locked=profile.state_locked,
    )


class LegacySource:
    """The Profile columns: stripe_subscription_id, subscription_status,
    stripe_customer_id, membership_plan and billing_method."""

    name = Source.LEGACY
    checks = CHECKS

    def load(self, profile_ids=None):
        profiles = Profile.objects.select_related("membership_plan")
        if profile_ids is not None:
            profiles = profiles.filter(pk__in=profile_ids)
        else:
            # A member with none of these set has nothing that can drift.
            profiles = profiles.filter(
                (Q(stripe_customer_id__isnull=False) & ~Q(stripe_customer_id=""))
                | (
                    Q(stripe_subscription_id__isnull=False)
                    & ~Q(stripe_subscription_id="")
                )
                | ~Q(subscription_status="inactive")
            )

        return [_from_columns(profile) for profile in profiles.order_by("pk")]


class SubscriptionSource:
    """Each member's current Subscription row, with the Profile columns that
    mirror it read in the same query."""

    name = Source.SUBSCRIPTIONS
    checks = SUBSCRIPTION_TABLE_CHECKS

    def load(self, profile_ids=None):
        profiles = Profile.objects.select_related(
            "membership_plan", "current_subscription__plan"
        )
        if profile_ids is not None:
            profiles = profiles.filter(pk__in=profile_ids)
        else:
            profiles = profiles.filter(
                has_billing_columns_q()
                | (Q(stripe_customer_id__isnull=False) & ~Q(stripe_customer_id=""))
            )
        live = dict(
            Subscription.objects.exclude(state=Subscription.State.CANCELLED)
            .values("payer")
            .annotate(total=Count("pk"))
            .values_list("payer", "total")
        )

        return [
            self._local(profile, live.get(profile.pk, 0))
            for profile in profiles.order_by("pk")
        ]

    def _local(self, profile, live_subscriptions):
        current = profile.current_subscription
        mirror = _from_columns(profile)
        if current is None:
            return LocalBilling(
                profile_id=profile.pk,
                name=mirror.name,
                customer_id=mirror.customer_id,
                subscription_id=None,
                status="inactive",
                price_id=None,
                billing_method=profile.billing_method,
                member_state=profile.state,
                state_locked=profile.state_locked,
                live_subscriptions=live_subscriptions,
                mirror=mirror,
            )
        return LocalBilling(
            profile_id=profile.pk,
            name=mirror.name,
            customer_id=mirror.customer_id,
            subscription_id=current.external_ref or None,
            status=current.legacy_status,
            price_id=current.plan.stripe_id if current.plan else None,
            billing_method=current.billing_method,
            member_state=profile.state,
            state_locked=profile.state_locked,
            subscription_pk=current.pk,
            subscription_state=current.state,
            live_subscriptions=live_subscriptions,
            mirror=mirror,
        )


SOURCES = (LegacySource(), SubscriptionSource())
