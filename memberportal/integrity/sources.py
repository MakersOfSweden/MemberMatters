"""Where the checks read what MemberMatters says about each subscription.

Today that is the five billing columns on Profile. When the refactored
Subscription and Payment tables land, a second source reads them into the same
LocalBilling shape and runs beside this one, and the two swap roles when the
new system takes over.
"""

from django.db.models import Q

from profile.models import Profile

from .models import Source
from .data import LocalBilling


class LegacySource:
    """The Profile columns: stripe_subscription_id, subscription_status,
    stripe_customer_id, membership_plan and billing_method."""

    name = Source.LEGACY

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

        return [
            LocalBilling(
                profile_id=profile.pk,
                name=profile.get_full_name(),
                customer_id=profile.stripe_customer_id or None,
                subscription_id=profile.stripe_subscription_id or None,
                status=profile.subscription_status,
                price_id=(
                    profile.membership_plan.stripe_id
                    if profile.membership_plan
                    else None
                ),
                billing_method=profile.billing_method,
                member_state=profile.state,
                state_locked=profile.state_locked,
            )
            for profile in profiles.order_by("pk")
        ]


SOURCES = (LegacySource(),)
