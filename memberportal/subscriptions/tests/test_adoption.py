"""Members from before the Subscription table: the data migration, the
adopt_billing_columns command and the test factory all give them rows that
describe their billing columns exactly, and never change the columns."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from profile.models import Profile
from subscriptions import records
from subscriptions.models import Subscription
from tests.factories import PaymentPlanFactory, ProfileFactory

# Every combination the columns are known to hold, consistent or not.
COLUMNS = [
    {"subscription_status": "active", "stripe_subscription_id": "sub_a"},
    {"subscription_status": "pending", "stripe_subscription_id": "sub_p"},
    {"subscription_status": "cancelling", "stripe_subscription_id": "sub_c"},
    {"subscription_status": "pending", "stripe_subscription_id": ""},
    {"subscription_status": "inactive", "stripe_subscription_id": "sub_stale"},
    {"subscription_status": "inactive", "stripe_subscription_id": None},
]


def members_from_before_the_table():
    members = [
        ProfileFactory(
            membership_plan=PaymentPlanFactory(), adopt_billing_columns=False, **columns
        )
        for columns in COLUMNS
    ]
    never_subscribed = ProfileFactory()
    ended = ProfileFactory(stripe_subscription_id=None)
    return members, [never_subscribed, ended]


def billing_columns():
    return {
        profile.pk: (
            profile.membership_plan_id,
            profile.stripe_subscription_id,
            profile.subscription_status,
        )
        for profile in Profile.objects.all()
    }


def assert_adopted(members, without_columns):
    for member in members:
        stored = Profile.objects.get(pk=member.pk)
        assert stored.current_subscription is not None
        assert records.mirror_matches(stored)
    for member in without_columns:
        assert not Subscription.objects.filter(payer=member).exists()


@pytest.mark.django_db
class TestFactory:
    def test_a_member_with_columns_gets_a_current_row(self):
        member = ProfileFactory(
            subscription_active=True, stripe_subscription_id="sub_1"
        )

        current = Profile.objects.get(pk=member.pk).current_subscription
        assert current.external_ref == "sub_1"
        assert current.legacy_status == "active"

    def test_rows_can_be_left_out(self):
        member = ProfileFactory(
            subscription_active=True,
            stripe_subscription_id="sub_1",
            adopt_billing_columns=False,
        )

        assert not member.subscriptions.exists()


@pytest.mark.django_db
class TestCommand:
    def run(self, *args):
        out = StringIO()
        call_command("adopt_billing_columns", *args, stdout=out)
        return out.getvalue()

    def test_adopts_members_without_rows(self):
        members, without_columns = members_from_before_the_table()
        before = billing_columns()

        output = self.run()

        assert f"Changed the subscriptions of {len(members)} of" in output
        assert_adopted(members, without_columns)
        assert billing_columns() == before

    def test_a_second_run_changes_nothing(self):
        members_from_before_the_table()
        self.run()
        rows = list(Subscription.objects.values())

        assert "Changed the subscriptions of 0 of" in self.run()
        assert list(Subscription.objects.values()) == rows

    def test_catches_up_with_a_write_by_older_code(self):
        member = ProfileFactory(
            subscription_active=True, stripe_subscription_id="sub_1"
        )
        # What the code before the table did on cancel: the columns only.
        Profile.objects.filter(pk=member.pk).update(subscription_status="cancelling")

        self.run()

        current = Profile.objects.get(pk=member.pk).current_subscription
        assert current.legacy_status == "cancelling"

    def test_a_dry_run_changes_nothing(self):
        members, _ = members_from_before_the_table()

        output = self.run("--dry-run")

        assert f"Would change the subscriptions of {len(members)} of" in output
        assert not Subscription.objects.exists()


def migrate(targets=None):
    executor = MigrationExecutor(connection)
    executor.migrate(targets or executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
class TestDataMigration:
    @pytest.fixture(autouse=True)
    def before_adoption(self, request):
        if request.config.getoption("nomigrations"):
            pytest.skip("needs real migrations; runs on the --migrations leg")
        migrate([("subscriptions", "0001_initial")])
        yield
        migrate()

    def test_adopts_every_member_with_columns(self):
        members, without_columns = members_from_before_the_table()
        before = billing_columns()

        migrate()

        assert_adopted(members, without_columns)
        assert billing_columns() == before

    def test_reversing_deletes_the_rows_and_keeps_the_columns(self):
        members_from_before_the_table()
        before = billing_columns()
        migrate()

        migrate([("subscriptions", "0001_initial")])

        assert not Subscription.objects.exists()
        assert billing_columns() == before
