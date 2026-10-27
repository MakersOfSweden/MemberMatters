"""The single writer: every function leaves the Profile columns exactly as the
code before the Subscription table did, None versus "" included, and the rows
saying the same."""

import pytest

from profile.models import Profile
from subscriptions import records
from subscriptions.models import Subscription
from tests.factories import PaymentPlanFactory, ProfileFactory

pytestmark = pytest.mark.django_db


def columns(profile):
    stored = Profile.objects.get(pk=profile.pk)
    return (
        stored.membership_plan_id,
        stored.stripe_subscription_id,
        stored.subscription_status,
    )


def locked(profile):
    return Profile.objects.select_for_update().get(pk=profile.pk)


def subscribed(status="active", subscription_id="sub_1", **fields):
    """A member as the code before the table left them, with no rows."""
    plan = fields.pop("membership_plan", None) or PaymentPlanFactory()
    return ProfileFactory(
        membership_plan=plan,
        stripe_subscription_id=subscription_id,
        subscription_status=status,
        adopt_billing_columns=False,
        **fields,
    )


class TestStart:
    def test_writes_the_columns_and_a_current_row(self):
        plan = PaymentPlanFactory()
        member = locked(ProfileFactory())

        started = records.start(
            member,
            external_ref="sub_new",
            plan=plan,
            billing_method="invoice",
            status="pending",
        )

        assert columns(member) == (plan.pk, "sub_new", "pending")
        assert Profile.objects.get(pk=member.pk).current_subscription == started
        started.refresh_from_db()
        assert started.state == Subscription.State.ACTIVE
        assert started.legacy_status == "pending"
        assert started.billing_method == "invoice"
        assert started.started_at is not None
        assert started.version == 1

    def test_replaces_a_subscription_still_current(self):
        # A member resuming a plan whose subscription is gone: the old code
        # overwrote the subscription id and kept the plan.
        member = subscribed(status="inactive", subscription_id=None)
        plan = member.membership_plan
        member = locked(member)

        started = records.start(
            member,
            external_ref="sub_new",
            plan=member.membership_plan,
            billing_method="card",
            status="active",
        )

        assert columns(member) == (plan.pk, "sub_new", "active")
        old = member.subscriptions.exclude(pk=started.pk).get()
        assert old.state == Subscription.State.CANCELLED
        assert old.cancelled_at is not None


class TestStatusChanges:
    def test_mark_cancelling_changes_only_the_status(self):
        member = subscribed()
        plan_id = member.membership_plan_id

        current = records.mark_cancelling(locked(member))

        assert columns(member) == (plan_id, "sub_1", "cancelling")
        assert current.state == Subscription.State.CANCELLING

    def test_mark_active_resumes(self):
        member = subscribed(status="cancelling")
        plan_id = member.membership_plan_id

        current = records.mark_active(locked(member))

        assert columns(member) == (plan_id, "sub_1", "active")
        assert current.state == Subscription.State.ACTIVE

    def test_pending_reads_as_active(self):
        member = subscribed(status="pending")

        records.adopt_profile_columns(locked(member))

        assert member.subscriptions.get().state == Subscription.State.ACTIVE

    def test_each_write_bumps_the_version(self):
        member = subscribed()

        first = records.mark_cancelling(locked(member)).version
        second = records.mark_active(locked(member)).version

        assert second == first + 1

    def test_needs_a_current_subscription(self):
        with pytest.raises(records.NoCurrentSubscription):
            records.mark_cancelling(locked(ProfileFactory()))


class TestEnd:
    def test_clears_the_columns_to_none(self):
        member = subscribed()

        ended = records.end(locked(member))

        assert columns(member) == (None, None, "inactive")
        assert Profile.objects.get(pk=member.pk).current_subscription is None
        assert ended.state == Subscription.State.CANCELLED
        assert ended.cancelled_at is not None

    def test_keeps_the_ended_row(self):
        member = subscribed()

        records.end(locked(member))

        assert member.subscriptions.get().external_ref == "sub_1"

    def test_with_nothing_current_still_clears_the_columns(self):
        member = ProfileFactory()
        assert member.stripe_subscription_id == ""

        assert records.end(locked(member)) is None
        assert columns(member) == (None, None, "inactive")


class TestAdoption:
    def test_copies_the_columns_verbatim(self):
        member = subscribed(status="pending", billing_method="invoice")
        before = columns(member)

        assert records.adopt_profile_columns(locked(member))

        assert columns(member) == before
        adopted = Profile.objects.get(pk=member.pk).current_subscription
        assert adopted.external_ref == "sub_1"
        assert adopted.legacy_status == "pending"
        assert adopted.billing_method == "invoice"
        assert adopted.plan_id == member.membership_plan_id
        assert adopted.started_at is None

    def test_is_idempotent(self):
        member = subscribed()
        records.adopt_profile_columns(locked(member))

        assert not records.adopt_profile_columns(locked(member))
        assert member.subscriptions.count() == 1

    def test_a_member_without_columns_gets_no_row(self):
        member = ProfileFactory()

        assert not records.adopt_profile_columns(locked(member))
        assert not member.subscriptions.exists()

    @pytest.mark.parametrize(
        "status, subscription_id, with_plan",
        [
            ("pending", "", False),
            ("cancelling", None, True),
            ("inactive", "sub_stale", False),
            ("inactive", None, True),
            ("active", "", True),
        ],
    )
    def test_inconsistent_columns_survive(self, status, subscription_id, with_plan):
        plan = PaymentPlanFactory() if with_plan else None
        member = ProfileFactory(
            membership_plan=plan,
            stripe_subscription_id=subscription_id,
            subscription_status=status,
            adopt_billing_columns=False,
        )
        before = columns(member)

        records.adopt_profile_columns(locked(member))
        records.sync_profile_mirror(locked(member))

        assert columns(member) == before

    def test_a_row_out_of_date_is_updated_in_place(self):
        member = subscribed()
        records.adopt_profile_columns(locked(member))
        Profile.objects.filter(pk=member.pk).update(subscription_status="cancelling")

        assert records.adopt_profile_columns(locked(member))

        current = member.subscriptions.get()
        assert current.legacy_status == "cancelling"
        assert current.state == Subscription.State.CANCELLING

    def test_another_subscription_id_closes_the_old_row(self):
        member = subscribed()
        records.adopt_profile_columns(locked(member))
        Profile.objects.filter(pk=member.pk).update(stripe_subscription_id="sub_2")

        records.adopt_profile_columns(locked(member))

        current = Profile.objects.get(pk=member.pk).current_subscription
        assert current.external_ref == "sub_2"
        old = member.subscriptions.get(external_ref="sub_1")
        assert old.state == Subscription.State.CANCELLED

    def test_emptied_columns_close_the_row(self):
        member = subscribed()
        records.adopt_profile_columns(locked(member))
        Profile.objects.filter(pk=member.pk).update(
            membership_plan=None,
            stripe_subscription_id="",
            subscription_status="inactive",
        )

        records.adopt_profile_columns(locked(member))

        assert Profile.objects.get(pk=member.pk).current_subscription is None
        assert member.subscriptions.get().state == Subscription.State.CANCELLED


class TestWritersAdoptFirst:
    def test_a_member_without_a_row_is_adopted_then_changed(self):
        member = subscribed()

        records.mark_cancelling(locked(member))

        current = member.subscriptions.get()
        assert current.legacy_status == "cancelling"
        assert current.external_ref == "sub_1"

    def test_columns_edited_past_the_writer_win(self):
        # What the code before the table did: write the status, leave the
        # rest as it found it.
        member = subscribed()
        records.adopt_profile_columns(locked(member))
        Profile.objects.filter(pk=member.pk).update(stripe_subscription_id="sub_2")

        records.mark_cancelling(locked(member))

        assert columns(member)[1:] == ("sub_2", "cancelling")
