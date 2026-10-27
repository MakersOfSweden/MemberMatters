"""The Subscription table as a second source: it is checked against the Profile
columns it mirrors, and against itself, while the Stripe checks keep running
against the columns alone."""

import dataclasses

import pytest

from integrity import runner
from integrity.checks import SUBSCRIPTION_TABLE_CHECKS, run_checks
from integrity.models import IntegrityIssue, IntegrityRun, Severity, Source
from integrity.sources import SubscriptionSource
from profile.models import Profile
from subscriptions.models import Subscription
from tests.factories import PaymentPlanFactory, ProfileFactory

from .test_checks import context, local

pytestmark = pytest.mark.django_db


def table_local(**overrides):
    """A member as the table source reads them, columns agreeing."""
    columns = local()
    values = dict(subscription_pk=7, subscription_state="active", mirror=columns)
    values.update(overrides)
    return dataclasses.replace(columns, **values)


def table_findings(*locals_):
    results = run_checks(
        context(list(locals_)), Source.SUBSCRIPTIONS, checks=SUBSCRIPTION_TABLE_CHECKS
    )
    return {
        name: findings
        for (_source, name), findings in results.findings.items()
        if findings
    }


class TestChecks:
    def test_a_table_agreeing_with_its_columns_trips_nothing(self):
        assert table_findings(table_local(live_subscriptions=1)) == {}

    @pytest.mark.parametrize(
        "field, value, label",
        [
            ("subscription_id", "sub_other", "subscription ID"),
            ("status", "cancelling", "status"),
            ("price_id", "price_yearly", "plan"),
        ],
    )
    def test_a_differing_column_is_a_mirror_mismatch(self, field, value, label):
        columns = dataclasses.replace(local(), **{field: value})

        [finding] = table_findings(table_local(mirror=columns))["mirror_mismatch"]

        assert finding.severity == Severity.CRITICAL
        assert finding.subscription_pk == 7
        assert finding.extra["differs"] == [label]

    def test_columns_without_a_row_are_a_mirror_mismatch(self):
        row_missing = table_local(
            subscription_id=None,
            status="inactive",
            price_id=None,
            subscription_pk=None,
            subscription_state=None,
        )

        assert table_findings(row_missing)["mirror_mismatch"]

    def test_two_live_subscriptions(self):
        [finding] = table_findings(table_local(live_subscriptions=2))[
            "several_live_subscriptions"
        ]

        assert finding.severity == Severity.CRITICAL

    def test_a_current_subscription_that_is_cancelled(self):
        columns = dataclasses.replace(local(), status="inactive")
        stale = table_local(
            status="inactive", subscription_state="cancelled", mirror=columns
        )

        [finding] = table_findings(stale)["current_subscription_cancelled"]

        assert finding.severity == Severity.WARNING


def member(**overrides):
    values = {
        "state": "active",
        "subscription_status": "active",
        "stripe_customer_id": "cus_anna",
        "stripe_subscription_id": "sub_anna",
        "membership_plan": PaymentPlanFactory(),
    }
    values.update(overrides)
    return ProfileFactory(**values)


class TestSource:
    def test_reads_the_current_row_and_the_columns(self):
        profile = member()

        [read] = SubscriptionSource().load()

        assert read.subscription_id == "sub_anna"
        assert read.status == "active"
        assert read.subscription_pk == profile.current_subscription.pk
        assert read.live_subscriptions == 1
        assert read.mirror.subscription_id == "sub_anna"

    def test_reads_a_member_with_columns_but_no_row(self):
        member(adopt_billing_columns=False)

        [read] = SubscriptionSource().load()

        assert read.subscription_pk is None
        assert read.mirror.subscription_id == "sub_anna"

    def test_leaves_out_a_member_with_nothing_set(self):
        ProfileFactory()

        assert SubscriptionSource().load() == []


class TestRun:
    def run(self):
        return runner.run(IntegrityRun.Trigger.SCHEDULE).run

    def test_a_member_in_sync_raises_nothing_from_either_source(
        self, billing_on, fake_stripe
    ):
        profile = member()
        fake_stripe.add("sub_anna", "cus_anna", profile.membership_plan.stripe_id)

        assert self.run().status == IntegrityRun.Status.COMPLETE
        assert not IntegrityIssue.objects.exists()

    def test_stripe_drift_is_reported_once(self, billing_on, fake_stripe):
        profile = member()
        fake_stripe.add(
            "sub_anna", "cus_anna", profile.membership_plan.stripe_id, status="unpaid"
        )

        self.run()

        [issue] = IntegrityIssue.objects.all()
        assert issue.check_name == "unpaid_but_active"
        assert issue.source == Source.LEGACY

    def test_finds_a_broken_mirror(self, billing_on, fake_stripe):
        profile = member()
        fake_stripe.add("sub_anna", "cus_anna", profile.membership_plan.stripe_id)
        subscription = Profile.objects.get(pk=profile.pk).current_subscription
        Subscription.objects.filter(pk=subscription.pk).update(
            legacy_status="cancelling"
        )

        self.run()

        [issue] = IntegrityIssue.objects.filter(check_name="mirror_mismatch")
        assert issue.source == Source.SUBSCRIPTIONS
        assert issue.subscription == subscription
        assert issue.profile == profile
