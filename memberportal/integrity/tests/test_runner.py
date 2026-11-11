"""A whole run against a fake Stripe: what it records, resolves and emails."""

import threading
import time
from datetime import timedelta

import pytest
import stripe
from constance.test import override_config
from django.db import connection
from django.forms.models import model_to_dict
from django.utils import timezone

from integrity import runner
from integrity.models import IntegrityIssue, IntegrityRun, Severity, Source
from integrity.store import issue_key
from profile.models import Profile
from tests.factories import PaymentPlanFactory, ProfileFactory

from .conftest import ADMIN_ADDRESS, admin_mail

pytestmark = pytest.mark.django_db


def member(subscription_id="sub_anna", customer="cus_anna", **overrides):
    values = {
        "state": "active",
        "subscription_status": "active",
        "billing_method": "card",
        "stripe_customer_id": customer,
        "stripe_subscription_id": subscription_id,
        "membership_plan": PaymentPlanFactory(),
    }
    values.update(overrides)
    return ProfileFactory(**values)


def run():
    return runner.run(IntegrityRun.Trigger.SCHEDULE).run


def open_checks():
    return sorted(
        IntegrityIssue.objects.filter(resolved_at__isnull=True).values_list(
            "check_name", flat=True
        )
    )


@pytest.fixture
def in_sync(billing_on, fake_stripe):
    """A member whose subscription agrees with Stripe."""
    profile = member()
    fake_stripe.add("sub_anna", "cus_anna", profile.membership_plan.stripe_id)
    return profile


class TestEnabled:
    def test_is_off_without_membership_billing(self, db):
        assert runner.is_enabled() is False

    def test_is_on_with_billing_and_a_key(self, billing_on):
        assert runner.is_enabled() is True

    def test_can_be_switched_off(self, billing_on):
        with override_config(BILLING_AUDIT_ENABLED=False):
            assert runner.is_enabled() is False


class TestRun:
    def test_a_member_in_sync_raises_nothing(self, in_sync, fake_stripe):
        result = run()

        assert result.status == IntegrityRun.Status.COMPLETE
        assert result.members_checked == 1
        assert open_checks() == []

    def test_one_listing_covers_every_live_subscription(self, billing_on, fake_stripe):
        for n in range(5):
            profile = member(f"sub_{n}", f"cus_{n}")
            fake_stripe.add(f"sub_{n}", f"cus_{n}", profile.membership_plan.stripe_id)

        run()

        assert len(fake_stripe.calls_to("Subscription.list")) == 1
        assert fake_stripe.calls_to("Subscription.retrieve") == []

    def test_a_subscription_missing_from_the_listing_is_fetched_alone(
        self, billing_on, fake_stripe
    ):
        profile = member()
        fake_stripe.add(
            "sub_anna",
            "cus_anna",
            profile.membership_plan.stripe_id,
            status="canceled",
            canceled_at=1_600_000_000,
        )

        run()

        # Once for the snapshot, and once more to confirm the critical issue.
        assert [call[1] for call in fake_stripe.calls_to("Subscription.retrieve")] == [
            ("sub_anna",),
            ("sub_anna",),
        ]
        assert open_checks() == ["ended_in_stripe"]

    def test_records_drift_as_an_issue(self, billing_on, fake_stripe):
        profile = member()
        fake_stripe.add(
            "sub_anna",
            "cus_anna",
            profile.membership_plan.stripe_id,
            status="canceled",
            canceled_at=1_600_000_000,
        )

        result = run()

        issue = IntegrityIssue.objects.get()
        assert issue.check_name == "ended_in_stripe"
        assert issue.severity == Severity.CRITICAL
        assert issue.source == Source.LEGACY
        assert issue.profile == profile
        assert issue.stripe_ref == "sub_anna"
        assert issue.details["mm"] == "active"
        assert issue.details["stripe"].startswith("canceled on")
        assert result.new_issues == 1
        assert result.open_issues == 1

    def test_the_same_drift_next_run_updates_the_same_issue(
        self, billing_on, fake_stripe
    ):
        profile = member()
        fake_stripe.add(
            "sub_anna", "cus_anna", profile.membership_plan.stripe_id, status="unpaid"
        )

        run()
        run()

        issue = IntegrityIssue.objects.get()
        assert issue.occurrences == 2

    def test_drift_that_is_fixed_resolves(self, in_sync, fake_stripe):
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"
        run()
        fake_stripe.subscriptions["sub_anna"]["status"] = "active"

        result = run()

        issue = IntegrityIssue.objects.get()
        assert issue.resolved_at is not None
        assert result.resolved_issues == 1

    def test_resolved_drift_that_returns_reopens_as_new(self, in_sync, fake_stripe):
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"
        run()
        IntegrityIssue.objects.update(
            acknowledged_at=timezone.now(), notified_severity=Severity.WARNING
        )
        fake_stripe.subscriptions["sub_anna"]["status"] = "active"
        run()
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"

        result = run()

        issue = IntegrityIssue.objects.get()
        assert issue.resolved_at is None
        assert issue.occurrences == 1
        assert issue.acknowledged_at is None
        assert issue.notified_severity == ""
        assert result.new_issues == 1

    def test_a_recent_stripe_change_waits_for_the_next_run(
        self, billing_on, fake_stripe
    ):
        profile = member()
        fake_stripe.add(
            "sub_anna",
            "cus_anna",
            profile.membership_plan.stripe_id,
            status="canceled",
            canceled_at=int(time.time()) - 60,
            ended_at=int(time.time()) - 60,
        )

        run()

        assert open_checks() == []

    def test_a_recent_change_leaves_an_open_issue_open(self, in_sync, fake_stripe):
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"
        run()
        fake_stripe.subscriptions["sub_anna"]["status"] = "active"
        fake_stripe.subscriptions["sub_anna"]["canceled_at"] = int(time.time()) - 60

        run()

        assert IntegrityIssue.objects.get().resolved_at is None

    def test_a_stripe_outage_fails_the_run_and_resolves_nothing(
        self, in_sync, fake_stripe
    ):
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"
        run()
        fake_stripe.subscriptions["sub_anna"]["status"] = "active"
        fake_stripe.errors["Subscription.list"] = stripe.error.APIError("down")

        result = run()

        assert result.status == IntegrityRun.Status.FAILED
        assert "Couldn't read subscriptions" in result.error
        assert IntegrityIssue.objects.get().resolved_at is None

    def test_a_restricted_key_without_webhook_access_still_completes(
        self, in_sync, fake_stripe
    ):
        fake_stripe.errors["WebhookEndpoint.list"] = stripe.error.PermissionError(
            "no permission"
        )

        result = run()

        assert result.status == IntegrityRun.Status.COMPLETE
        assert [entry["check"] for entry in result.skipped_checks] == [
            "webhook_endpoint"
        ]

    def test_a_failed_price_fetch_makes_the_run_incomplete(self, in_sync, fake_stripe):
        fake_stripe.errors["Price.retrieve"] = stripe.error.APIError("down")

        result = run()

        assert result.status == IntegrityRun.Status.INCOMPLETE

    def test_refuses_to_start_while_another_run_is_running(self, in_sync):
        IntegrityRun.objects.create(trigger=IntegrityRun.Trigger.SCHEDULE)

        with pytest.raises(runner.AlreadyRunning):
            run()

    def test_one_run_at_a_time_member_rechecks_included(self, in_sync):
        recheck = IntegrityRun.objects.create(
            trigger=IntegrityRun.Trigger.MEMBER, profile=in_sync
        )

        with pytest.raises(runner.AlreadyRunning):
            run()
        recheck.delete()
        IntegrityRun.objects.create(trigger=IntegrityRun.Trigger.SCHEDULE)
        with pytest.raises(runner.AlreadyRunning):
            runner.run(IntegrityRun.Trigger.MEMBER, profile=in_sync)

    def test_a_dry_run_doesnt_wait_for_a_running_run(self, in_sync, fake_stripe):
        IntegrityRun.objects.create(trigger=IntegrityRun.Trigger.SCHEDULE)

        outcome = runner.run(IntegrityRun.Trigger.COMMAND, dry_run=True)

        assert outcome.run.status == IntegrityRun.Status.COMPLETE

    def test_a_run_that_died_is_marked_failed(self, in_sync):
        dead = IntegrityRun.objects.create(
            trigger=IntegrityRun.Trigger.SCHEDULE,
            started_at=timezone.now() - timedelta(hours=3),
        )

        run()

        dead.refresh_from_db()
        assert dead.status == IntegrityRun.Status.FAILED

    def test_counts_its_stripe_requests(self, in_sync, fake_stripe):
        result = run()

        assert result.stripe_requests == len(fake_stripe.calls)

    def test_a_dry_run_writes_nothing(self, billing_on, fake_stripe, outbox):
        profile = member()
        fake_stripe.add(
            "sub_anna", "cus_anna", profile.membership_plan.stripe_id, status="unpaid"
        )

        outcome = runner.run(IntegrityRun.Trigger.COMMAND, dry_run=True)

        assert IntegrityRun.objects.count() == 0
        assert IntegrityIssue.objects.count() == 0
        assert outbox == []
        [(_source, _ctx, results)] = outcome.checked
        assert results.findings[(Source.LEGACY, "unpaid_but_active")]


@pytest.fixture
def after_listing(fake_stripe, monkeypatch):
    """Runs a change right after Stripe lists the subscriptions, as if it
    happened while the run was reading Stripe."""
    changes = []
    listing = fake_stripe.subscription_list

    def list_then_change(**params):
        page = listing(**params)
        while changes:
            changes.pop()()
        return page

    monkeypatch.setattr(stripe.Subscription, "list", list_then_change)
    return changes.append


class TestConfirmation:
    """A critical finding is read again before it's recorded, so a change made
    while the run read Stripe isn't reported as drift."""

    def test_a_member_who_cancels_mid_run_isnt_reported(
        self, in_sync, fake_stripe, after_listing, outbox
    ):
        def cancel():
            fake_stripe.subscriptions["sub_anna"].update(
                cancel_at_period_end=True, canceled_at=int(time.time())
            )
            Profile.objects.filter(pk=in_sync.pk).update(
                subscription_status="cancelling"
            )

        after_listing(cancel)

        result = run()

        assert open_checks() == []
        assert result.status == IntegrityRun.Status.COMPLETE

    def test_a_subscription_that_ends_mid_run_isnt_reported(
        self, in_sync, fake_stripe, after_listing
    ):
        def end():
            fake_stripe.subscriptions["sub_anna"].update(
                status="canceled", ended_at=int(time.time())
            )
            Profile.objects.filter(pk=in_sync.pk).update(
                subscription_status="inactive",
                stripe_subscription_id=None,
                membership_plan=None,
            )

        after_listing(end)

        run()

        assert open_checks() == []

    def test_leaves_the_members_open_issues_as_they_are(
        self, in_sync, fake_stripe, after_listing
    ):
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"
        run()

        def end():
            fake_stripe.subscriptions["sub_anna"]["status"] = "canceled"
            Profile.objects.filter(pk=in_sync.pk).update(
                subscription_status="cancelling"
            )

        after_listing(end)

        run()

        issue = IntegrityIssue.objects.get()
        assert issue.check_name == "unpaid_but_active"
        assert issue.resolved_at is None
        assert issue.occurrences == 1

    def test_a_real_critical_issue_is_recorded(self, billing_on, fake_stripe):
        profile = member(subscription_status="cancelling")
        fake_stripe.add("sub_anna", "cus_anna", profile.membership_plan.stripe_id)

        result = run()

        assert open_checks() == ["cancel_not_scheduled"]
        assert [call[1] for call in fake_stripe.calls_to("Subscription.retrieve")] == [
            ("sub_anna",)
        ]
        assert result.stripe_requests == len(fake_stripe.calls)

    def test_one_that_cant_be_confirmed_waits_for_the_next_run(
        self, billing_on, fake_stripe
    ):
        profile = member(subscription_status="cancelling")
        fake_stripe.add("sub_anna", "cus_anna", profile.membership_plan.stripe_id)
        fake_stripe.errors["Subscription.retrieve"] = stripe.error.APIError("down")

        result = run()

        assert open_checks() == []
        assert result.status == IntegrityRun.Status.INCOMPLETE
        assert "couldn't confirm sub_anna" in result.skipped_checks[0]["reason"]


def undelivered(event_id, customer="cus_anna"):
    return {
        "id": event_id,
        "object": "event",
        "type": "invoice.paid",
        "created": 1_600_000_000,
        "data": {"object": {"id": f"in_{event_id}", "customer": customer}},
    }


class TestAnIssueThatGrows:
    """An acknowledged issue covering several things (undelivered events) asks
    for attention again when it comes to cover a new one."""

    @pytest.fixture
    def acknowledged_event(self, in_sync, fake_stripe):
        fake_stripe.events = [undelivered("evt_1")]
        run()
        IntegrityIssue.objects.update(acknowledged_at=timezone.now())

    def test_stays_acknowledged_while_it_covers_the_same(
        self, acknowledged_event, fake_stripe
    ):
        run()

        assert IntegrityIssue.objects.get().acknowledged_at is not None

    def test_a_new_event_clears_the_acknowledgement(
        self, acknowledged_event, fake_stripe
    ):
        fake_stripe.events = [undelivered("evt_1"), undelivered("evt_2")]

        run()

        issue = IntegrityIssue.objects.get()
        assert issue.acknowledged_at is None
        assert issue.occurrences == 2

    def test_an_event_that_drops_out_changes_nothing(
        self, acknowledged_event, fake_stripe
    ):
        fake_stripe.events = [undelivered("evt_1"), undelivered("evt_2")]
        run()
        IntegrityIssue.objects.update(acknowledged_at=timezone.now())
        fake_stripe.events = [undelivered("evt_2")]

        run()

        assert IntegrityIssue.objects.get().acknowledged_at is not None


@pytest.mark.django_db(transaction=True)
def test_two_runs_starting_at_once_cant_both_start(monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("needs two connections to one database: the Postgres leg")
    holding, release = threading.Event(), threading.Event()
    mark_dead_runs = runner.mark_dead_runs

    def first_holds_the_lock(now):
        mark_dead_runs(now)
        if not holding.is_set():
            holding.set()
            release.wait(5)

    monkeypatch.setattr(runner, "mark_dead_runs", first_holds_the_lock)
    outcomes = []

    def start():
        try:
            runner.start(
                IntegrityRun(trigger=IntegrityRun.Trigger.SCHEDULE), timezone.now()
            )
            outcomes.append("started")
        except runner.AlreadyRunning:
            outcomes.append("refused")
        finally:
            connection.close()

    first = threading.Thread(target=start)
    first.start()
    assert holding.wait(5)
    second = threading.Thread(target=start)
    second.start()
    second.join(0.5)
    assert second.is_alive(), "the second run didn't wait for the lock"
    release.set()
    first.join(5)
    second.join(5)

    assert sorted(outcomes) == ["refused", "started"]
    assert IntegrityRun.objects.count() == 1


class TestMemberRecheck:
    def test_fetches_only_that_members_customer(self, billing_on, fake_stripe):
        profile = member()
        fake_stripe.add("sub_anna", "cus_anna", profile.membership_plan.stripe_id)

        runner.run(IntegrityRun.Trigger.MEMBER, profile=profile)

        [listing] = fake_stripe.calls_to("Subscription.list")
        assert listing[2]["customer"] == "cus_anna"
        assert fake_stripe.calls_to("Price.retrieve") == []
        assert fake_stripe.calls_to("WebhookEndpoint.list") == []

    def test_resolves_only_that_members_issues(self, billing_on, fake_stripe):
        anna = member("sub_anna", "cus_anna")
        erik = member("sub_erik", "cus_erik")
        fake_stripe.add(
            "sub_anna", "cus_anna", anna.membership_plan.stripe_id, status="unpaid"
        )
        fake_stripe.add(
            "sub_erik", "cus_erik", erik.membership_plan.stripe_id, status="unpaid"
        )
        run()
        fake_stripe.subscriptions["sub_anna"]["status"] = "active"
        fake_stripe.subscriptions["sub_erik"]["status"] = "active"

        runner.run(IntegrityRun.Trigger.MEMBER, profile=anna)

        assert IntegrityIssue.objects.get(profile=anna).resolved_at is not None
        assert IntegrityIssue.objects.get(profile=erik).resolved_at is None

    def test_sends_no_email(self, billing_on, fake_stripe, outbox):
        profile = member()
        fake_stripe.add(
            "sub_anna",
            "cus_anna",
            profile.membership_plan.stripe_id,
            status="canceled",
            canceled_at=1_600_000_000,
        )

        runner.run(IntegrityRun.Trigger.MEMBER, profile=profile)

        assert admin_mail(outbox) == []


class TestReadOnly:
    """A run must never change what it checks. A repair would hide the bug
    that caused the drift, and a buggy one would run unattended against
    membership and money."""

    def test_changes_no_member_and_writes_nothing_to_stripe(
        self, billing_on, fake_stripe, outbox
    ):
        drifted = [
            member("sub_a", "cus_a"),
            member("sub_b", "cus_b", subscription_status="cancelling"),
            member("sub_c", "cus_c", subscription_status="pending"),
            member("sub_d", "cus_d", state="inactive"),
        ]
        price = drifted[0].membership_plan.stripe_id
        fake_stripe.add("sub_a", "cus_a", price, status="canceled", canceled_at=1)
        fake_stripe.add("sub_b", "cus_b", drifted[1].membership_plan.stripe_id)
        fake_stripe.add("sub_c", "cus_c", drifted[2].membership_plan.stripe_id)
        fake_stripe.add("sub_d", "cus_d", drifted[3].membership_plan.stripe_id)
        fake_stripe.add("sub_orphan", "cus_gone", price)
        before = [model_to_dict(profile) for profile in Profile.objects.order_by("pk")]

        run()

        after = [model_to_dict(profile) for profile in Profile.objects.order_by("pk")]
        assert after == before
        assert fake_stripe.writes == []
        assert len(open_checks()) >= 5
        assert {message["To"] for message in outbox} == {ADMIN_ADDRESS}


class TestEmails:
    def test_the_first_run_sends_one_summary(self, billing_on, fake_stripe, outbox):
        for n in range(3):
            profile = member(f"sub_{n}", f"cus_{n}")
            fake_stripe.add(
                f"sub_{n}",
                f"cus_{n}",
                profile.membership_plan.stripe_id,
                status="canceled",
                canceled_at=1,
            )

        run()

        [mail] = admin_mail(outbox)
        assert mail["Subject"] == "First billing check: 3 critical"
        assert (
            IntegrityIssue.objects.filter(notified_severity=Severity.CRITICAL).count()
            == 3
        )

    def test_the_first_run_says_so_when_all_is_well(self, in_sync, outbox):
        run()

        [mail] = admin_mail(outbox)
        assert mail["Subject"] == "First billing check: no issues found"
        assert "found nothing wrong" in mail["HtmlBody"]

    def test_a_new_critical_issue_is_emailed_once(self, in_sync, fake_stripe, outbox):
        run()
        outbox.clear()
        fake_stripe.subscriptions["sub_anna"].update(status="canceled", canceled_at=1)

        run()
        run()

        [mail] = admin_mail(outbox)
        assert mail["Subject"] == "Billing check: 1 new critical issue"
        assert "Cancelled in Stripe, still active here" in mail["HtmlBody"]
        assert "dashboard.stripe.com/test/subscriptions/sub_anna" in mail["HtmlBody"]
        assert f"/manage/members/{in_sync.user_id}" in mail["HtmlBody"]

    def test_a_new_warning_waits_for_the_digest(self, in_sync, fake_stripe, outbox):
        run()
        outbox.clear()
        fake_stripe.subscriptions["sub_anna"]["status"] = "unpaid"

        run()

        assert admin_mail(outbox) == []

    def test_an_acknowledged_critical_issue_is_not_emailed(
        self, in_sync, fake_stripe, outbox
    ):
        run()
        outbox.clear()
        fake_stripe.subscriptions["sub_anna"].update(status="canceled", canceled_at=1)
        IntegrityIssue.objects.create(
            key=issue_key(Source.LEGACY, "ended_in_stripe", f"profile:{in_sync.pk}"),
            check_name="ended_in_stripe",
            severity=Severity.CRITICAL,
            source=Source.LEGACY,
            message="Cancelled in Stripe, still active here",
            profile=in_sync,
            acknowledged_at=timezone.now(),
        )

        run()

        issue = IntegrityIssue.objects.get()
        assert issue.resolved_at is None
        assert issue.occurrences == 2
        assert admin_mail(outbox) == []

    def test_a_disabled_endpoint_is_emailed_after_missing_events(
        self, in_sync, fake_stripe, outbox
    ):
        run()
        fake_stripe.endpoints[0]["enabled_events"] = ["invoice.paid"]
        run()
        IntegrityIssue.objects.update(acknowledged_at=timezone.now())
        outbox.clear()
        fake_stripe.endpoints[0]["status"] = "disabled"

        run()

        [mail] = admin_mail(outbox)
        assert "Stripe webhook endpoint is disabled" in mail["HtmlBody"]
        assert open_checks() == ["webhook_endpoint"]

    def test_a_failing_streak_emails_at_its_start_and_end(
        self, in_sync, fake_stripe, outbox
    ):
        run()
        outbox.clear()
        fake_stripe.errors["Subscription.list"] = stripe.error.AuthenticationError(
            "bad key"
        )

        run()
        run()
        del fake_stripe.errors["Subscription.list"]
        run()

        assert [mail["Subject"] for mail in admin_mail(outbox)] == [
            "Billing check failed",
            "Billing check is working again",
        ]
        assert "Stripe refused the secret key" in admin_mail(outbox)[0]["HtmlBody"]

    def test_issue_text_is_escaped(self, billing_on, fake_stripe, outbox):
        profile = member(first_name="<b>Anna</b>")
        fake_stripe.add(
            "sub_anna",
            "cus_anna",
            profile.membership_plan.stripe_id,
            status="canceled",
            canceled_at=1,
        )

        run()

        [mail] = admin_mail(outbox)
        assert "<b>Anna</b>" not in mail["HtmlBody"]
        assert "&lt;b&gt;Anna&lt;/b&gt;" in mail["HtmlBody"]
