"""The Subscription table and the Profile's pointer at the current row.

The pointer is a one-to-one rather than a flag on the row because MySQL has no
partial unique index: "at most one current subscription per member, and no
row current for two members" has to be something the schema enforces on every
backend.
"""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from profile.models import Profile
from subscriptions.models import Subscription
from tests.factories import PaymentPlanFactory, ProfileFactory

pytestmark = pytest.mark.django_db


def subscription(payer, **fields):
    fields.setdefault("state", Subscription.State.ACTIVE)
    fields.setdefault("legacy_status", "active")
    return Subscription.objects.create(payer=payer, **fields)


class TestSubscription:
    def test_a_member_can_have_several(self):
        member = ProfileFactory()
        subscription(member, state=Subscription.State.CANCELLED)
        subscription(member)

        assert member.subscriptions.count() == 2

    def test_null_and_empty_references_are_kept_apart(self):
        # The mirror writes external_ref back into stripe_subscription_id,
        # which holds both.
        member = ProfileFactory()
        empty = subscription(member, external_ref="")
        missing = subscription(member, external_ref=None)

        empty.refresh_from_db()
        missing.refresh_from_db()
        assert empty.external_ref == ""
        assert missing.external_ref is None

    def test_is_live_until_cancelled(self):
        member = ProfileFactory()

        assert subscription(member).is_live
        assert subscription(member, state=Subscription.State.CANCELLING).is_live
        assert not subscription(member, state=Subscription.State.CANCELLED).is_live

    def test_deleting_the_payer_deletes_their_subscriptions(self):
        member = ProfileFactory()
        subscription(member)

        member.user.delete()

        assert not Subscription.objects.exists()

    def test_a_plan_with_subscriptions_cannot_be_deleted(self):
        plan = PaymentPlanFactory()
        subscription(ProfileFactory(), plan=plan)

        with pytest.raises(ProtectedError):
            plan.delete()


class TestCurrentSubscription:
    def test_defaults_to_none(self):
        assert ProfileFactory().current_subscription is None

    def test_points_at_one_row(self):
        member = ProfileFactory()
        row = subscription(member)

        member.current_subscription = row
        member.save(update_fields=["current_subscription"])

        assert Profile.objects.get(pk=member.pk).current_subscription == row

    def test_a_row_is_current_for_one_member_at_most(self):
        row = subscription(ProfileFactory())
        first, second = ProfileFactory(), ProfileFactory()
        first.current_subscription = row
        first.save(update_fields=["current_subscription"])

        second.current_subscription = row
        with pytest.raises(IntegrityError), transaction.atomic():
            second.save(update_fields=["current_subscription"])

    def test_deleting_the_row_clears_the_pointer(self):
        member = ProfileFactory()
        row = subscription(member)
        member.current_subscription = row
        member.save(update_fields=["current_subscription"])

        row.delete()

        assert Profile.objects.get(pk=member.pk).current_subscription is None
